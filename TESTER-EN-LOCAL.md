# Tester Reserva sur votre poste Windows, puis déployer par GitHub

## 1. Récupérer le code

Dans PowerShell, dans le dossier de votre choix :

```powershell
git clone https://github.com/Like-Lejeune/reserva.git
cd reserva
```

## 2. Lancer

Double-cliquez sur **`lancer-local.cmd`**, ou dans PowerShell :

```powershell
.\lancer-local.cmd -Tests
```

La première fois, le script installe ce qui manque (uv, qui fournit Python 3.12, et Node.js, par
winget), les dépendances, puis compile le site : comptez 5 à 10 minutes. Les fois suivantes, il
démarre en moins d'une minute. Le navigateur s'ouvre sur **http://localhost:8000**.

| Option | Effet |
|---|---|
| `-Tests` | lance d'abord les 24 tests du serveur |
| `-InstallerPdf` | installe GTK (MSYS2), sans lequel le PDF ne se génère pas sous Windows |
| `-Installer` | réinstalle les dépendances, après un `git pull` |
| `-Port 8080` | si le port 8000 est déjà pris |

Ce poste de test est réglé ainsi (fichier `backend\.env`, créé au premier lancement) :
- **paiements simulés** : chaque paiement réussit aussitôt, sans débit et sans clé TrustChange ;
- **le 695 249 549 est administrateur** ;
- les codes « mot de passe oublié » s'affichent dans la fenêtre du serveur ;
- la base et les photos de test sont dans `backend\data` : supprimez ce dossier pour repartir de zéro.

**Le PDF sous Windows.** Il demande les bibliothèques GTK. Sans elles, tout le reste fonctionne et
le bouton « Voir le PDF » affiche un message clair. Pour l'activer : `.\lancer-local.cmd -InstallerPdf`
(une dizaine de minutes). Sur le serveur, il fonctionne sans rien faire.

## 3. Ce qu'il faut vérifier (un quart d'heure)

1. **La vitrine** : logo, quatre offres, tableau comparatif, numéros WhatsApp en bas de page.
2. **Inscription** avec le 695 249 549 : l'onglet « Administration » apparaît à gauche.
3. **Un rapport** : « Nouveau rapport », puis « Ajouter un défaut » avec une photo et une phrase
   comme « fuite sous l'évier de la cuisine ». Le corps de métier, le lieu et la gravité se remplissent.
4. **Sans connexion** : touche F12, onglet Réseau, « Hors connexion ». Ajoutez un défaut : il
   attend, puis part quand vous rétablissez la connexion.
5. **Une correction** : ouvrez un défaut, « C'est corrigé », ajoutez la photo « après ».
6. **Le PDF et le partage** (avec GTK).
7. **L'abonnement** dans « Mon compte » : essai de 14 jours, puis paiement simulé de l'offre Pro.
   Le crédit IA augmente de 500 FCFA.
8. **Mon espace** : logo et coordonnées. **Artisans** : ajoutez-en un, puis « Préparer l'envoi » ;
   le lien WhatsApp contient ses défauts.
9. **Mot de passe oublié** : le code s'affiche dans la fenêtre du serveur.
10. **L'administration** : comptes, paiements, création d'un code promo.

L'appareil photo du téléphone et la dictée demandent le HTTPS : ils se testent sur le serveur.

Notez ce qui ne va pas (capture et étapes) et envoyez-le-moi : je corrige, je pousse sur GitHub.

## 4. Déployer sur le serveur depuis GitHub

Quand le test local est bon, connecté au serveur en SSH :

```bash
curl -fsSL https://raw.githubusercontent.com/Like-Lejeune/reserva/main/deploy/installer.sh -o installer.sh
sudo bash installer.sh
```

Le script clone le dépôt dans `/opt/reserva`, compile le site sur le serveur et installe tout.
La suite (domaine, clé TrustChange, sauvegardes) est dans [`DEPLOIEMENT.md`](DEPLOIEMENT.md).

**Après une correction** poussée sur GitHub : sur votre poste, `git pull` puis
`.\lancer-local.cmd -Installer` pour la tester ; sur le serveur,
`sudo bash /opt/reserva/deploy/mettre-a-jour.sh`.
