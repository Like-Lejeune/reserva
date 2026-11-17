"""Configuration lue depuis l'environnement (préfixe RESERVA_) ou un fichier .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESERVA_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str = ""  # vide -> sqlite dans data_dir
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- IA : "rules" (hors ligne, sans clé) ou "openai" (tout serveur compatible OpenAI) ---
    ai_provider: str = "rules"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_llm_model: str = "gpt-4o-mini"
    ai_asr_model: str = "whisper-1"

    # --- Envoi : "console" (journal), "whatsapp" (Cloud API) ou "sms" (passerelle HTTP) ---
    dispatch_channel: str = "console"
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    sms_gateway_url: str = ""
    sms_api_key: str = ""
    sms_sender: str = "RESERVA"

    public_base_url: str = "http://localhost:8000"
    web_dir: Path = Path("../web/dist")  # application mobile compilée, servie par ce même serveur

    # --- Environnement : "dev" ou "production" (en production, le démarrage refuse les réglages dangereux) ---
    env: str = "dev"

    # --- Envoi des codes (mot de passe oublié) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    default_country_code: str = "237"  # ajouté aux numéros saisis sans indicatif, pour les SMS
    reset_code_minutes: int = 15

    # --- Sécurité ---
    secret_key: str = "a-changer-en-production"  # signe les sessions et les liens de partage
    token_days: int = 30
    share_link_days: int = 30
    billing_secret: str = ""  # secret du serveur de paiement ; vide = recharge désactivée

    # --- Paiement Mobile Money (TrustChange) ---
    trustchange_api_key: str = ""  # vide = paiement en ligne inactif
    trustchange_base_url: str = "https://api.trustchange.fr"
    trustchange_webhook_secret: str = ""
    trustchange_callback_url: str = ""  # https://votre-domaine/api/payments/webhook
    trustchange_signature_header: str = "X-TrustChange-Signature"  # à vérifier dans la documentation TrustChange
    trustchange_timestamp_header: str = "X-TrustChange-Timestamp"
    payment_simulation: bool = False  # développement uniquement : sans clé, tout paiement réussit aussitôt
    trial_days: int = 14
    topup_min_fcfa: int = 500

    # --- Tarifs IA : prix du fournisseur, convertis en FCFA puis majorés de la marge ---
    ai_usd_per_mtok_in: float = 0.15
    ai_usd_per_mtok_out: float = 0.60
    ai_usd_per_audio_min: float = 0.006
    usd_to_fcfa: float = 600.0
    ai_margin_pct: float = 30.0
    admin_logins: list[str] = []  # identifiants (téléphone en chiffres ou e-mail) des administrateurs de la plateforme
    welcome_credit_fcfa: int = 500  # crédit offert à la création du cabinet

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'reserva.db'}"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.media_dir.mkdir(parents=True, exist_ok=True)
    return s
