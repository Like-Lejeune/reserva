import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';
import '../store.dart';
import '../widgets.dart';

String _date(String iso) {
  const months = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  final d = DateTime.parse(iso).toLocal();
  return '${d.day} ${months[d.month - 1]} ${d.year}';
}

/// Mon abonnement : où j'en suis, changer ou renouveler, payer par Mobile Money, recharger le crédit IA.
class SubscriptionScreen extends StatefulWidget {
  const SubscriptionScreen({super.key});

  @override
  State<SubscriptionScreen> createState() => _SubscriptionScreenState();
}

class _SubscriptionScreenState extends State<SubscriptionScreen> {
  Map<String, dynamic>? _sub;
  List<Map<String, dynamic>> _plans = [];
  List<Map<String, dynamic>> _operators = [];
  Map<String, dynamic>? _quote;
  String _period = 'mois';
  String _chosen = '';
  String _operator = '';
  String _error = '';
  String _notice = '';
  String _phase = 'idle'; // idle | sending | waiting
  Timer? _timer;
  final _promo = TextEditingController();
  final _phone = TextEditingController();

  @override
  void initState() {
    super.initState();
    final login = Api.session.value?.login ?? '';
    if (RegExp(r'^\d+$').hasMatch(login)) _phone.text = login;
    _load();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _promo.dispose();
    _phone.dispose();
    super.dispose();
  }

  bool get _busy => _phase != 'idle';

  Future<void> _load() async {
    try {
      final sub = await Api.get('/subscription') as Map<String, dynamic>;
      final plans = ((await Api.get('/plans')) as List).cast<Map<String, dynamic>>();
      var operators = _operators;
      if (sub['payments_enabled'] == true && operators.isEmpty) {
        operators = ((await Api.get('/payments/operators')) as List).cast<Map<String, dynamic>>();
      }
      if (!mounted) return;
      setState(() {
        _sub = sub;
        _plans = plans;
        _operators = operators;
        if (_operator.isEmpty && operators.isNotEmpty) _operator = operators.first['code'] as String;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.offline ? "L'abonnement se gère avec une connexion." : e.message);
    }
  }

  /// Le prix affiché vient toujours du serveur : remise, déduction des jours déjà payés, dates.
  Future<void> _refreshQuote() async {
    if (_chosen.isEmpty) return;
    try {
      final q = await Api.post('/subscription/quote', {'plan': _chosen, 'period': _period, 'promo_code': _promo.text.trim()});
      if (mounted) {
        setState(() {
          _quote = q as Map<String, dynamic>;
          _error = '';
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _quote = null;
          _error = e.message;
        });
      }
    }
  }

  void _paid() {
    setState(() {
      _phase = 'idle';
      _chosen = '';
      _quote = null;
      _notice = 'Paiement reçu. Merci !';
    });
    _load();
    unawaited(store.sync()); // met à jour l'offre affichée ailleurs
  }

  void _failed(String message) => setState(() {
        _phase = 'idle';
        _error = message.isEmpty ? "Le paiement n'a pas abouti." : message;
      });

  /// Après l'envoi, l'utilisateur valide sur son téléphone ; on interroge toutes les 3 s, 3 minutes au plus.
  void _follow(String id, int tries) {
    _timer = Timer(const Duration(seconds: 3), () async {
      if (!mounted) return;
      try {
        final p = await Api.get('/payments/$id') as Map<String, dynamic>;
        if (!mounted) return;
        if (p['status'] == 'reussi') return _paid();
        if (p['status'] == 'echoue') return _failed((p['message'] ?? '') as String);
      } on ApiException {
        // réseau instable : on réessaie
      }
      if (!mounted) return;
      if (tries >= 60) {
        return _failed("Pas encore de confirmation. Si vous avez validé, l'offre s'activera toute seule dans quelques minutes.");
      }
      _follow(id, tries + 1);
    });
  }

  Future<void> _pay(String path, Map<String, Object?> body) async {
    setState(() {
      _phase = 'sending';
      _error = '';
      _notice = '';
    });
    try {
      final p = await Api.post(path, body) as Map<String, dynamic>;
      if (!mounted) return;
      if (p['status'] == 'reussi') return _paid();
      if (p['status'] == 'echoue') return _failed((p['message'] ?? '') as String);
      setState(() => _phase = 'waiting');
      _follow(p['id'] as String, 0);
    } on ApiException catch (e) {
      if (mounted) _failed(e.message);
    }
  }

  Future<void> _trial(String plan) async {
    try {
      await Api.post('/subscription/trial', {'plan': plan});
      if (!mounted) return;
      setState(() => _notice = 'Essai gratuit démarré.');
      await _load();
      unawaited(store.sync());
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _topup() async {
    var amount = 2000;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (context) => StatefulBuilder(
        builder: (context, setSheet) => Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Recharger mon crédit IA', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
              const SizedBox(height: 12),
              SegmentedButton<int>(
                segments: [for (final a in [1000, 2000, 5000]) ButtonSegment(value: a, label: Text(fcfa(a)))],
                selected: {amount},
                onSelectionChanged: (s) => setSheet(() => amount = s.first),
              ),
              const SizedBox(height: 16),
              FilledButton(onPressed: () => Navigator.pop(context, true), child: Text('Recharger ${fcfa(amount)}')),
            ],
          ),
        ),
      ),
    );
    if (ok == true) await _pay('/billing/topup', {'amount_fcfa': amount, 'phone': _phone.text.trim(), 'operator': _operator});
  }

  Widget _box({required Widget child, Color border = const Color(0xFFDFE3E8), Color? color, double width = 1}) => Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: color ?? Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: border, width: width),
        ),
        child: child,
      );

  Widget _billLine(String label, String value, {bool total = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Flexible(child: Text(label, style: TextStyle(fontWeight: total ? FontWeight.w800 : FontWeight.w400, fontSize: total ? 17 : 15))),
            Text(value, style: TextStyle(fontWeight: total ? FontWeight.w800 : FontWeight.w400, fontSize: total ? 17 : 15)),
          ],
        ),
      );

  @override
  Widget build(BuildContext context) {
    final sub = _sub;
    return Scaffold(
      appBar: AppBar(title: const Text('Mon abonnement', style: TextStyle(fontWeight: FontWeight.w800))),
      body: sub == null
          ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(_error.isEmpty ? 'Chargement…' : _error, textAlign: TextAlign.center)))
          : ListView(padding: const EdgeInsets.all(16), children: _content(sub)),
    );
  }

  List<Widget> _content(Map<String, dynamic> sub) {
    final daysLeft = sub['days_left'] as int?;
    final soon = sub['expires_soon'] == true;
    final paid = sub['paid'] == true;
    final enabled = sub['payments_enabled'] == true && _operators.isNotEmpty;
    final q = _quote;
    final payments = ((sub['payments'] ?? []) as List).cast<Map<String, dynamic>>();

    return [
      _box(
        border: soon ? const Color(0xFFC98A1A) : (paid ? okGreen : const Color(0xFFDFE3E8)),
        color: soon ? const Color(0xFFFFF8EA) : null,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Flexible(
                  child: Text('Offre ${sub['plan_label']}${sub['source'] == 'essai' ? ' (essai gratuit)' : ''}',
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                ),
                if (daysLeft != null) Text(daysLeft == 0 ? 'Dernier jour' : '$daysLeft jour${daysLeft > 1 ? 's' : ''} restant${daysLeft > 1 ? 's' : ''}'),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              sub['until'] != null
                  ? "Valable jusqu'au ${_date(sub['until'] as String)}. Sans renouvellement, votre compte repasse en Gratuit et rien n'est supprimé."
                  : (paid ? 'Sans date de fin.' : 'Gratuit, sans limite de durée.'),
              style: const TextStyle(color: muted, fontSize: 13),
            ),
          ],
        ),
      ),
      SegmentedButton<String>(
        segments: const [
          ButtonSegment(value: 'mois', label: Text('Mensuel')),
          ButtonSegment(value: 'an', label: Text('Annuel, 2 mois offerts')),
        ],
        selected: {_period},
        onSelectionChanged: _busy
            ? null
            : (s) {
                setState(() => _period = s.first);
                _refreshQuote();
              },
      ),
      const SizedBox(height: 12),
      for (final p in _plans.where((p) => (p['price_fcfa'] as num) > 0))
        _box(
          border: _chosen == p['key'] ? brand : const Color(0xFFDFE3E8),
          width: _chosen == p['key'] ? 2 : 1,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(p['label'] as String, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                  Text('${fcfa((_period == 'an' ? (p['price_year_fcfa'] ?? (p['price_fcfa'] as num) * 10) : p['price_fcfa']) as num)} par $_period'),
                ],
              ),
              const SizedBox(height: 4),
              Text(((p['features'] as List).take(3)).join(', '), style: const TextStyle(color: muted, fontSize: 13)),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _busy
                          ? null
                          : () {
                              setState(() {
                                _chosen = _chosen == p['key'] ? '' : p['key'] as String;
                                _quote = null;
                                _notice = '';
                              });
                              _refreshQuote();
                            },
                      child: Text(p['key'] == sub['plan'] ? 'Renouveler' : 'Choisir'),
                    ),
                  ),
                  if (sub['trial_available'] == true) ...[
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton(
                        onPressed: _busy ? null : () => _trial(p['key'] as String),
                        child: Text('Essayer ${sub['trial_days']} jours'),
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ),
        ),
      if (_chosen.isNotEmpty)
        _box(
          color: const Color(0xFFF4F5F7),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (q != null) ...[
                _billLine('Offre ${q['plan_label']}, ${q['period_label']}', fcfa(q['base_fcfa'] as num)),
                if ((q['discount_fcfa'] as num) > 0) _billLine('Code ${q['promo_code']}', '- ${fcfa(q['discount_fcfa'] as num)}'),
                if ((q['prorata_fcfa'] as num) > 0) _billLine("Déjà payé sur l'offre en cours", '- ${fcfa(q['prorata_fcfa'] as num)}'),
                const Divider(),
                _billLine('À payer', fcfa(q['amount_fcfa'] as num), total: true),
                Text(
                  '${q['renewal'] == true ? 'Prolonge votre offre' : 'Valable'} du ${_date(q['starts_at'] as String)} au ${_date(q['ends_at'] as String)}.',
                  style: const TextStyle(color: muted, fontSize: 13),
                ),
                const SizedBox(height: 10),
              ],
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _promo,
                      textCapitalization: TextCapitalization.characters,
                      decoration: const InputDecoration(labelText: 'Code promo (facultatif)'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  SizedBox(width: 110, child: OutlinedButton(onPressed: _busy ? null : _refreshQuote, child: const Text('Appliquer'))),
                ],
              ),
              const SizedBox(height: 12),
              if (enabled) ...[
                ..._payFields(),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: _busy || q == null || _phone.text.trim().isEmpty
                      ? null
                      : () => _pay('/subscription/checkout', {
                            'plan': _chosen,
                            'period': _period,
                            'phone': _phone.text.trim(),
                            'operator': _operator,
                            'promo_code': (q['promo_code'] ?? '') as String,
                          }),
                  child: Text(_phase == 'sending' ? 'Envoi…' : (q == null ? 'Payer' : 'Payer ${fcfa(q['amount_fcfa'] as num)}')),
                ),
              ] else
                const Text("Le paiement en ligne n'est pas encore disponible. Contactez-nous pour activer cette offre.",
                    style: TextStyle(color: muted)),
            ],
          ),
        ),
      if (_phase == 'waiting')
        _box(
          color: const Color(0xFFFFF4DC),
          border: const Color(0xFFFFF4DC),
          child: const Text('Validez le paiement sur votre téléphone. Cet écran se met à jour tout seul.', style: TextStyle(fontWeight: FontWeight.w600)),
        ),
      if (_notice.isNotEmpty)
        _box(
          color: const Color(0xFFE3F3E4),
          border: const Color(0xFFE3F3E4),
          child: Text(_notice, style: const TextStyle(color: okGreen, fontWeight: FontWeight.w600)),
        ),
      if (_error.isNotEmpty) Padding(padding: const EdgeInsets.only(bottom: 12), child: Text(_error, style: const TextStyle(color: warnRed))),
      if (enabled && _chosen.isEmpty) ...[
        ..._payFields(),
        const SizedBox(height: 12),
        OutlinedButton(
          onPressed: _busy || _phone.text.trim().isEmpty ? null : _topup,
          child: const Text('Recharger mon crédit IA'),
        ),
        const SizedBox(height: 12),
      ],
      if (payments.isNotEmpty) ...[
        const Text('Mes paiements', style: TextStyle(fontWeight: FontWeight.w700)),
        for (final p in payments)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(p['label'] as String),
            subtitle: Text(_date(p['created_at'] as String)),
            trailing: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(fcfa(p['amount_fcfa'] as num)),
                Text(
                  p['status'] == 'reussi' ? 'Payé' : (p['status'] == 'echoue' ? 'Échoué' : 'En attente'),
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: p['status'] == 'reussi' ? okGreen : (p['status'] == 'echoue' ? warnRed : const Color(0xFF8A5A00)),
                  ),
                ),
              ],
            ),
          ),
      ],
    ];
  }

  /// Opérateur + numéro Mobile Money, communs à l'abonnement et à la recharge.
  List<Widget> _payFields() => [
        DropdownButtonFormField<String>(
          value: _operator.isEmpty ? null : _operator,
          decoration: const InputDecoration(labelText: 'Opérateur'),
          items: [for (final o in _operators) DropdownMenuItem(value: o['code'] as String, child: Text(o['name'] as String))],
          onChanged: _busy ? null : (v) => setState(() => _operator = v ?? _operator),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _phone,
          keyboardType: TextInputType.phone,
          decoration: const InputDecoration(labelText: 'Numéro Mobile Money', hintText: '6XX XX XX XX'),
          onChanged: (_) => setState(() {}),
        ),
      ];
}
