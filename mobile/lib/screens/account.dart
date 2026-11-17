import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';
import '../store.dart';
import '../widgets.dart';
import 'subscription.dart';

/// Mon compte : mon offre, mes compteurs de consommation, les autres offres, me déconnecter.
class AccountScreen extends StatefulWidget {
  const AccountScreen({super.key});

  @override
  State<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends State<AccountScreen> {
  Map<String, dynamic>? _usage;
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final usage = await Api.get('/account/usage') as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _usage = usage;
        _offline = false;
      });
    } on ApiException {
      if (mounted) setState(() => _offline = true);
    }
  }

  Future<void> _logout() async {
    if (store.pending > 0) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Se déconnecter ?'),
          content: Text("${store.pending} élément(s) ne sont pas encore envoyés. Ils resteront sur ce téléphone."),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Annuler')),
            TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Se déconnecter')),
          ],
        ),
      );
      if (ok != true) return;
    }
    if (mounted) Navigator.of(context).popUntil((route) => route.isFirst);
    await store.logout();
  }

  Widget _card(List<Widget> children) => Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
          ),
        ),
      );

  Widget _stat(String value, String label) => Expanded(
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 3),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: const Color(0xFFF4F5F7), borderRadius: BorderRadius.circular(10)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
              Text(label, style: const TextStyle(color: muted, fontSize: 12)),
            ],
          ),
        ),
      );

  String _subscriptionLine(Map sub) {
    final days = sub['days_left'] as int?;
    final label = 'Offre ${sub['plan_label']}${sub['source'] == 'essai' ? ' (essai gratuit)' : ''}';
    if (days == null) return sub['paid'] == true ? '$label, sans date de fin.' : '$label, sans limite de durée.';
    return days == 0 ? '$label, dernier jour.' : '$label, encore $days jour${days > 1 ? 's' : ''}.';
  }

  String _money(num v) => '${v.toStringAsFixed(v == v.roundToDouble() ? 0 : 1).replaceAll('.', ',')} F';

  @override
  Widget build(BuildContext context) {
    final session = Api.session.value;
    if (session == null) return const SizedBox.shrink();
    final u = _usage;
    const title = TextStyle(fontSize: 17, fontWeight: FontWeight.w800);

    return Scaffold(
      appBar: AppBar(title: const Text('Mon compte', style: TextStyle(fontWeight: FontWeight.w800))),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _card([
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(session.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                        Text(session.login, style: const TextStyle(color: muted)),
                      ],
                    ),
                  ),
                  Chip2('Offre ${u != null ? (u['plan'] as Map)['label'] : session.planLabel}', background: brand, color: Colors.white),
                ],
              ),
            ]),
            if (u == null)
              Padding(
                padding: const EdgeInsets.only(bottom: 14),
                child: Text(
                  _offline ? "Vos compteurs s'afficheront au retour de la connexion." : 'Chargement de votre consommation…',
                  style: const TextStyle(color: muted),
                ),
              )
            else ...[
              _card([
                const Text('Ma consommation', style: title),
                const SizedBox(height: 12),
                Meter(
                  label: 'Photos stockées',
                  used: (u['storage'] as Map)['used_bytes'] as num,
                  limit: (u['storage'] as Map)['limit_bytes'] as num?,
                  format: bytesLabel,
                ),
                const SizedBox(height: 14),
                Meter(label: 'Rapports', used: (u['reports'] as Map)['used'] as num, limit: (u['reports'] as Map)['limit'] as num?),
                if ((((u['members'] as Map)['limit'] as num?) ?? 2) > 1) ...[
                  const SizedBox(height: 14),
                  Meter(label: 'Membres', used: (u['members'] as Map)['used'] as num, limit: (u['members'] as Map)['limit'] as num?),
                ],
                const SizedBox(height: 14),
                Row(
                  children: [
                    _stat('${u['defects']}', 'défauts notés'),
                    _stat('${u['defects_fixed']}', 'corrigés'),
                    _stat('${u['photos']}', 'photos'),
                  ],
                ),
              ]),
              _card([
                const Text('Assistance IA', style: title),
                const SizedBox(height: 10),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('Crédit restant'),
                    Text(
                      fcfa((((u['ai'] as Map)['balance_fcfa'] as num)).clamp(0, double.infinity)),
                      style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    _stat('${((u['ai'] as Map)['month'] as Map)['calls']}', 'notes classées ce mois'),
                    _stat(_money(((u['ai'] as Map)['month'] as Map)['spent_fcfa'] as num), 'dépensés ce mois'),
                    _stat(_money(((u['ai'] as Map)['total'] as Map)['spent_fcfa'] as num), 'depuis le début'),
                  ],
                ),
                const SizedBox(height: 10),
                const Text(
                  "Le crédit sert quand l'IA classe vos notes. À zéro, l'application continue de fonctionner avec un classement plus simple.",
                  style: TextStyle(color: muted, fontSize: 13),
                ),
              ]),
              _card([
                const Text('Mon abonnement', style: title),
                const SizedBox(height: 8),
                Text(_subscriptionLine(u['subscription'] as Map), style: const TextStyle(color: muted)),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () async {
                    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const SubscriptionScreen()));
                    await _load();
                  },
                  child: Text((u['subscription'] as Map)['paid'] == true ? 'Renouveler ou changer d\'offre' : 'Voir les offres'),
                ),
              ]),
            ],
            OutlinedButton(onPressed: _logout, child: const Text('Se déconnecter')),
          ],
        ),
      ),
    );
  }
}
