"""Envoi des codes à usage unique (mot de passe oublié) : SMS pour un numéro, e-mail pour une adresse.

Sans passerelle configurée, rien n'est envoyé : l'utilisateur est invité à nous contacter, et
l'administration peut lui générer un code à transmettre de vive voix.
"""

import smtplib
from email.message import EmailMessage

from app.config import Settings, get_settings
from app.dispatch import SmsHttpChannel


def delivery_for(login: str, s: Settings | None = None) -> str:
    """Canal qui servirait pour cet identifiant : "sms", "email" ou "aucun". Ne dit rien de l'existence du compte."""
    s = s or get_settings()
    if "@" in login:
        return "email" if s.smtp_host else "aucun"
    return "sms" if s.sms_gateway_url else "aucun"


def international(phone_digits: str, s: Settings) -> str:
    """Les identifiants sont souvent saisis sans indicatif : on ajoute celui du pays par défaut."""
    return phone_digits if len(phone_digits) > 9 else f"{s.default_country_code}{phone_digits}"


def send_code(login: str, code: str) -> bool:
    """Envoie le code. Renvoie False si aucun canal n'est configuré ou si l'envoi échoue."""
    s = get_settings()
    text = f"Reserva : votre code est {code}. Il est valable {s.reset_code_minutes} minutes. Ne le communiquez à personne."
    channel = delivery_for(login, s)
    if channel == "sms":
        ok, _ = SmsHttpChannel(s).send(international(login, s), text)
        return ok
    if channel == "email":
        message = EmailMessage()
        message["Subject"] = "Votre code Reserva"
        message["From"] = s.smtp_from or s.smtp_user
        message["To"] = login
        message.set_content(text)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(message)
            return True
        except (smtplib.SMTPException, OSError):
            return False
    if s.env != "production":
        print(f"[code de réinitialisation, non envoyé] {login} : {code}")
    return False
