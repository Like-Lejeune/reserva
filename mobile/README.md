# Reserva — application mobile Flutter

Même application que la version web : rapports, défauts avec photo et dictée, travail hors connexion,
synchronisation, PDF à partager, compteurs de consommation.

**État : code écrit mais jamais compilé.** Le SDK Flutter n'a pas pu être installé dans l'environnement
où ce code a été produit. Attendez-vous à quelques erreurs à corriger au premier `flutter analyze`.

## Mise en route

Flutter 3.27 ou plus récent.

```bash
cd reserva/mobile
flutter create . --platforms android,ios --project-name reserva --org cm.reserva   # crée android/ et ios/
flutter pub get
flutter analyze
flutter run --dart-define=API_URL=https://votre-domaine.com
```

Sans `API_URL`, l'application vise `http://10.0.2.2:8000` (le serveur local vu depuis l'émulateur Android).

## Autorisations à ajouter après `flutter create`

### Android — `android/app/src/main/AndroidManifest.xml`, dans `<manifest>` :

```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.CAMERA"/>
<uses-permission android:name="android.permission.RECORD_AUDIO"/>
<queries>
  <intent><action android:name="android.speech.RecognitionService"/></intent>
  <intent><action android:name="android.intent.action.VIEW"/><data android:scheme="https"/></intent>
</queries>
```

Pour tester contre un serveur en `http://` (sans HTTPS), ajouter `android:usesCleartextTraffic="true"`
à la balise `<application>`. À retirer en production.

### iOS — `ios/Runner/Info.plist` :

```xml
<key>NSCameraUsageDescription</key>
<string>Pour photographier les défauts du chantier.</string>
<key>NSMicrophoneUsageDescription</key>
<string>Pour dicter la description d'un défaut.</string>
<key>NSSpeechRecognitionUsageDescription</key>
<string>Pour transformer votre dictée en texte.</string>
```

## Organisation du code

| Fichier | Rôle |
|---|---|
| `lib/main.dart` | Démarrage, thème, bascule connexion / rapports, envoi automatique |
| `lib/api.dart` | Appels au serveur, session gardée sur le téléphone |
| `lib/store.dart` | Base locale SQLite et synchronisation (hors connexion d'abord) |
| `lib/models.dart` | Rapport, défaut, photo, libellés |
| `lib/widgets.dart` | Bandeau d'état, photo, jauge, étiquettes |
| `lib/screens/login.dart` | Inscription et connexion |
| `lib/screens/reports.dart` | Mes rapports |
| `lib/screens/report.dart` | Un rapport : défauts, PDF, partage, suppression |
| `lib/screens/add_defect.dart` | Nouveau défaut : photo + note dictée ou tapée |
| `lib/screens/defect.dart` | Détail, correction avec photo « après », modification |
| `lib/screens/account.dart` | Mon compte : offre, compteurs de consommation |
| `lib/screens/subscription.dart` | Abonnement : offres, essai, paiement Mobile Money, recharge, historique |
