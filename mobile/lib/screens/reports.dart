import 'package:flutter/material.dart';

import '../api.dart';
import '../store.dart';
import '../widgets.dart';
import 'account.dart';
import 'report.dart';

/// Accueil : la liste des rapports et un bouton pour en créer un. Seul le nom est demandé.
class ReportsScreen extends StatelessWidget {
  const ReportsScreen({super.key});

  void _open(BuildContext context, Widget screen) =>
      Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));

  Future<void> _create(BuildContext context) async {
    final name = TextEditingController();
    final client = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Nouveau rapport'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: name,
              autofocus: true,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(labelText: 'Nom du chantier', hintText: 'Ex. Villa Odza'),
            ),
            const SizedBox(height: 12),
            TextField(controller: client, decoration: const InputDecoration(labelText: 'Client (facultatif)')),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Annuler')),
          FilledButton(
            style: FilledButton.styleFrom(minimumSize: const Size(96, 44)),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Créer'),
          ),
        ],
      ),
    );
    if (ok != true || name.text.trim().isEmpty) return;
    final project = await store.createProject(name.text.trim(), client: client.text.trim());
    if (context.mounted) _open(context, ReportScreen(projectId: project.id));
  }

  @override
  Widget build(BuildContext context) {
    final session = Api.session.value;
    final first = (session?.name ?? '').split(' ').first;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mes rapports', style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          IconButton(
            tooltip: 'Mon compte',
            onPressed: () => _open(context, const AccountScreen()),
            icon: CircleAvatar(
              backgroundColor: brand,
              child: Text(first.isEmpty ? '?' : first[0].toUpperCase(), style: const TextStyle(color: Colors.white)),
            ),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Column(
        children: [
          SyncBanner(onSeePlans: () => _open(context, const AccountScreen())),
          Expanded(
            child: RefreshIndicator(
              onRefresh: store.sync,
              child: Live<List<ProjectSummary>>(
                load: store.listProjects,
                builder: (context, projects) => ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(16),
                  children: [
                    FilledButton.icon(
                      onPressed: () => _create(context),
                      icon: const Icon(Icons.add),
                      label: const Text('Nouveau rapport'),
                    ),
                    const SizedBox(height: 14),
                    if (projects.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(32),
                        child: Text(
                          "Aucun rapport pour l'instant. Créez-en un, puis ajoutez vos photos de défauts.",
                          textAlign: TextAlign.center,
                          style: TextStyle(color: muted),
                        ),
                      ),
                    for (final s in projects)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: Card(
                          clipBehavior: Clip.antiAlias,
                          child: InkWell(
                            onTap: () => _open(context, ReportScreen(projectId: s.project.id)),
                            child: Padding(
                              padding: const EdgeInsets.all(14),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text(s.project.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                                        const SizedBox(height: 3),
                                        Text(
                                          s.total == 0
                                              ? 'Aucun défaut noté'
                                              : '${s.done} sur ${s.total} corrigé${s.done > 1 ? 's' : ''}',
                                          style: const TextStyle(color: muted),
                                        ),
                                        if (s.total > 0) ...[
                                          const SizedBox(height: 8),
                                          ClipRRect(
                                            borderRadius: BorderRadius.circular(4),
                                            child: LinearProgressIndicator(
                                              value: s.done / s.total,
                                              minHeight: 8,
                                              color: okGreen,
                                              backgroundColor: const Color(0xFFE3E7EC),
                                            ),
                                          ),
                                        ],
                                      ],
                                    ),
                                  ),
                                  const Icon(Icons.chevron_right, color: muted),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
