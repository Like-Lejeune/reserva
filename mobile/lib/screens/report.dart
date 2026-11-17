import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../models.dart';
import '../store.dart';
import '../widgets.dart';
import 'account.dart';
import 'add_defect.dart';
import 'defect.dart';

class _ReportData {
  _ReportData(this.project, this.defects, this.photos);
  final Project? project;
  final List<Defect> defects;
  final Map<String, Photo?> photos;
}

/// Un rapport : la liste des défauts, un gros bouton pour en ajouter, et le PDF à partager.
class ReportScreen extends StatefulWidget {
  const ReportScreen({super.key, required this.projectId});

  final String projectId;

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  bool _busy = false;

  Future<_ReportData> _load() async {
    final project = await store.getProject(widget.projectId);
    final defects = await store.listDefects(widget.projectId);
    final photos = <String, Photo?>{};
    for (final d in defects) {
      final all = await store.listPhotos(d.id);
      final before = all.where((p) => p.kind == 'photo_avant');
      photos[d.id] = before.isNotEmpty ? before.first : (all.isNotEmpty ? all.first : null);
    }
    return _ReportData(project, defects, photos);
  }

  void _say(String message) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));

  /// Lien du PDF, lisible sans compte pendant 30 jours.
  Future<String?> _pdfLink() async {
    setState(() => _busy = true);
    try {
      await store.sync(); // le PDF doit contenir ce qui vient d'être saisi
      final res = await Api.post('/projects/${widget.projectId}/share') as Map<String, dynamic>;
      final query = Uri.parse(res['url'] as String).query;
      return '$apiUrl/api/public/report.pdf?$query';
    } on ApiException catch (e) {
      _say(e.offline ? 'Le PDF se prépare sur le serveur : il faut une connexion.' : e.message);
      return null;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openPdf() async {
    final url = await _pdfLink();
    if (url != null) await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  }

  Future<void> _share(Project project, int remaining) async {
    final url = await _pdfLink();
    if (url == null) return;
    await Share.share('Rapport de finition, ${project.name} : $remaining défaut(s) à corriger.\n$url');
  }

  Future<void> _delete(Project project, int count) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Supprimer ce rapport ?'),
        content: Text('« ${project.name} » sera supprimé avec ses $count défaut(s) et ses photos.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Annuler')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Supprimer', style: TextStyle(color: warnRed))),
        ],
      ),
    );
    if (ok != true) return;
    await store.deleteProject(project.id);
    if (mounted) Navigator.of(context).pop();
  }

  void _open(Widget screen) => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));

  @override
  Widget build(BuildContext context) {
    return Live<_ReportData>(
      load: _load,
      builder: (context, data) {
        final project = data.project;
        if (project == null || project.deleted) {
          return Scaffold(appBar: AppBar(), body: const Center(child: Text('Rapport introuvable.')));
        }
        final defects = data.defects;
        final done = defects.where((d) => d.done).length;
        return Scaffold(
          appBar: AppBar(
            title: Text(project.name, style: const TextStyle(fontWeight: FontWeight.w800)),
            actions: [
              PopupMenuButton<String>(
                onSelected: (_) => _delete(project, defects.length),
                itemBuilder: (context) => const [PopupMenuItem(value: 'delete', child: Text('Supprimer ce rapport'))],
              ),
            ],
          ),
          floatingActionButtonLocation: FloatingActionButtonLocation.centerFloat,
          floatingActionButton: FloatingActionButton.extended(
            backgroundColor: brand,
            foregroundColor: Colors.white,
            onPressed: () => _open(AddDefectScreen(projectId: project.id)),
            icon: const Icon(Icons.add_a_photo_outlined),
            label: const Text('Ajouter un défaut', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          ),
          body: Column(
            children: [
              SyncBanner(onSeePlans: () => _open(const AccountScreen())),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                  children: [
                    Text(
                      defects.isEmpty
                          ? 'Aucun défaut noté'
                          : '$done sur ${defects.length} corrigé${done > 1 ? 's' : ''}'
                              '${project.client.isNotEmpty ? ', ${project.client}' : ''}',
                      style: const TextStyle(color: muted),
                    ),
                    if (defects.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(
                          value: done / defects.length,
                          minHeight: 8,
                          color: okGreen,
                          backgroundColor: const Color(0xFFE3E7EC),
                        ),
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(child: OutlinedButton(onPressed: _busy ? null : _openPdf, child: const Text('Voir le PDF'))),
                          const SizedBox(width: 10),
                          Expanded(
                            child: FilledButton(
                              onPressed: _busy ? null : () => _share(project, defects.length - done),
                              child: const Text('Partager'),
                            ),
                          ),
                        ],
                      ),
                    ] else
                      const Padding(
                        padding: EdgeInsets.all(32),
                        child: Text(
                          'Prenez une photo du premier défaut : appuyez sur le bouton en bas.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: muted),
                        ),
                      ),
                    const SizedBox(height: 14),
                    for (final d in defects)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: Opacity(
                          opacity: d.done ? 0.7 : 1,
                          child: Card(
                            clipBehavior: Clip.antiAlias,
                            child: InkWell(
                              onTap: () => _open(DefectScreen(defectId: d.id)),
                              child: Padding(
                                padding: const EdgeInsets.all(12),
                                child: Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    PhotoView(photo: data.photos[d.id], size: 64),
                                    const SizedBox(width: 12),
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            d.description.isNotEmpty
                                                ? d.description
                                                : (d.transcript.isNotEmpty ? d.transcript : 'Défaut sans description'),
                                            maxLines: 2,
                                            overflow: TextOverflow.ellipsis,
                                            style: const TextStyle(fontWeight: FontWeight.w700),
                                          ),
                                          const SizedBox(height: 2),
                                          Text(
                                            [
                                              if (d.number > 0) 'N° ${d.number}',
                                              d.needsAi ? 'Classement en attente' : (lots[d.lot] ?? d.lot),
                                              if (d.location.isNotEmpty) d.location,
                                            ].join(', '),
                                            style: const TextStyle(color: muted, fontSize: 13),
                                          ),
                                          const SizedBox(height: 6),
                                          Wrap(
                                            spacing: 6,
                                            runSpacing: 4,
                                            children: [
                                              Chip2.status(d.status),
                                              if (d.severity == 'majeure' && !d.done) Chip2(severities[d.severity]!, background: accent),
                                              if (d.severity == 'bloquante' && !d.done)
                                                Chip2(severities[d.severity]!, background: warnRed, color: Colors.white),
                                              if (d.dirty) const Chip2('Non envoyé'),
                                            ],
                                          ),
                                        ],
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
