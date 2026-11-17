import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../store.dart';
import '../widgets.dart';

/// Un seul écran : trois champs pour créer un compte, deux pour se connecter.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _name = TextEditingController();
  final _login = TextEditingController();
  final _password = TextEditingController();
  bool _creating = true;
  bool _busy = false;
  String _error = '';

  @override
  void dispose() {
    _name.dispose();
    _login.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_login.text.trim().isEmpty || _password.text.length < 6 || (_creating && _name.text.trim().isEmpty)) {
      setState(() => _error = 'Remplissez tous les champs (mot de passe : 6 caractères minimum).');
      return;
    }
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      final res = await Api.post(
        _creating ? '/auth/register' : '/auth/login',
        _creating
            ? {'name': _name.text.trim(), 'login': _login.text.trim(), 'password': _password.text}
            : {'login': _login.text.trim(), 'password': _password.text},
      );
      await Api.setSession(Session.fromJson(res as Map<String, dynamic>));
      unawaited(store.sync());
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const SizedBox(height: 48),
            Center(
              child: Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(16)),
                child: const Icon(Icons.check_rounded, color: accent, size: 52),
              ),
            ),
            const SizedBox(height: 12),
            const Text('Reserva', textAlign: TextAlign.center, style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
            const Text('Vos rapports de finition, en quelques photos.', textAlign: TextAlign.center, style: TextStyle(color: muted)),
            const SizedBox(height: 24),
            if (_creating) ...[
              TextField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(labelText: 'Votre nom'),
              ),
              const SizedBox(height: 12),
            ],
            TextField(
              controller: _login,
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Téléphone ou e-mail'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _password,
              obscureText: true,
              decoration: InputDecoration(labelText: 'Mot de passe', helperText: _creating ? '6 caractères minimum' : null),
              onSubmitted: (_) => _submit(),
            ),
            if (_error.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(_error, style: const TextStyle(color: warnRed)),
            ],
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: Text(_busy ? 'Un instant…' : (_creating ? 'Commencer' : 'Se connecter')),
            ),
            TextButton(
              onPressed: () => setState(() {
                _creating = !_creating;
                _error = '';
              }),
              child: Text(_creating ? "J'ai déjà un compte" : 'Créer un compte'),
            ),
          ],
        ),
      ),
    );
  }
}
