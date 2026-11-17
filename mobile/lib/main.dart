import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'screens/login.dart';
import 'screens/reports.dart';
import 'store.dart';
import 'widgets.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
  runApp(const ReservaApp());
}

class ReservaApp extends StatefulWidget {
  const ReservaApp({super.key});

  @override
  State<ReservaApp> createState() => _ReservaAppState();
}

class _ReservaAppState extends State<ReservaApp> with WidgetsBindingObserver {
  Timer? _timer;
  final _navigator = GlobalKey<NavigatorState>();

  /// Session terminée (déconnexion ou expiration) : on referme les écrans ouverts pour revenir à la connexion.
  void _onSession() {
    if (Api.session.value == null) _navigator.currentState?.popUntil((route) => route.isFirst);
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    Api.session.addListener(_onSession);
    // Envoi automatique : au démarrage, au retour dans l'application, puis chaque minute.
    unawaited(store.sync());
    _timer = Timer.periodic(const Duration(minutes: 1), (_) => unawaited(store.sync()));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    Api.session.removeListener(_onSession);
    _timer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(store.sync());
  }

  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(seedColor: brand, primary: brand);
    return MaterialApp(
      title: 'Reserva',
      navigatorKey: _navigator,
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: scheme,
        scaffoldBackgroundColor: const Color(0xFFF4F5F7),
        appBarTheme: const AppBarTheme(backgroundColor: Color(0xFFF4F5F7), surfaceTintColor: Colors.transparent),
        // Boutons grands, faciles à toucher sur un chantier
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            minimumSize: const Size.fromHeight(54),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            minimumSize: const Size.fromHeight(52),
            backgroundColor: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        ),
        cardTheme: CardThemeData(
          color: Colors.white,
          elevation: 0,
          margin: EdgeInsets.zero,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
            side: const BorderSide(color: Color(0xFFDFE3E8)),
          ),
        ),
      ),
      // Connecté : mes rapports. Sinon : l'écran d'inscription. Le changement de session bascule tout seul.
      home: ValueListenableBuilder<Session?>(
        valueListenable: Api.session,
        builder: (context, session, _) =>
            session == null ? const LoginScreen() : ReportsScreen(key: ValueKey(session.orgId)),
      ),
    );
  }
}
