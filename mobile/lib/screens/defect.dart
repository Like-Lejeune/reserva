import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../models.dart';
import '../store.dart';
import '../widgets.dart';

class _DefectData {
  _DefectData(this.defect, this.photos);
  final Defect? defect;
  final List<Photo> photos;
}

/// Détail d'un défaut : le corriger (avec photo « après »), ou ajuster ce que l'IA a rempli.
class DefectScreen extends StatefulWidget {
  const DefectScreen({super.key, required this.defectId});

  final String defectId;

  @override
  State<DefectScreen> createState() => _DefectScreenState();
}

class _DefectScreenState extends State<DefectScreen> {
  final _picker = ImagePicker();

  Future<_DefectData> _load() async =>
      _DefectData(await store.getDefect(widget.defectId), await store.listPhotos(widget.defectId));

  Future<String?> _shoot() async {
    final shot = await _picker.pickImage(source: ImageSource.camera, maxWidth: 1600, maxHeight: 1600, imageQuality: 80);
    return shot?.path;
  }

  Future<void> _setStatus(Defect d, String status) async {
    d.status = status;
    await store.saveDefect(d);
  }

  /// La photo « après » sert de preuve : pas de « corrigé » sans elle.
  Future<void> _markFixed(Defect d, String doneStatus) async {
    final path = await _shoot();
    if (path == null) return;
    await store.addPhoto(d.id, 'photo_apres', path);
    await _setStatus(d, doneStatus);
  }

  Future<void> _delete(Defect d) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Supprimer ce défaut du rapport ?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Annuler')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Supprimer', style: TextStyle(color: warnRed))),
        ],
      ),
    );
    if (ok != true) return;
    d.deleted = true;
    await store.saveDefect(d);
    if (mounted) Navigator.of(context).pop();
  }

  Future<void> _edit(Defect d) async {
    final description = TextEditingController(text: d.description);
    final location = TextEditingController(text: d.location);
    final action = TextEditingController(text: d.action);
    var lot = lots.containsKey(d.lot) ? d.lot : 'autre';
    var severity = d.severity;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (context) => StatefulBuilder(
        builder: (context, setSheet) => Padding(
          padding: EdgeInsets.fromLTRB(16, 0, 16, MediaQuery.of(context).viewInsets.bottom + 16),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(controller: description, minLines: 2, maxLines: 4, decoration: const InputDecoration(labelText: 'Description')),
                const SizedBox(height: 12),
                TextField(controller: location, decoration: const InputDecoration(labelText: 'Lieu', hintText: 'Ex. Cuisine')),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: lot,
                  decoration: const InputDecoration(labelText: 'Corps de métier'),
                  items: [for (final e in lots.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                  onChanged: (v) => setSheet(() => lot = v ?? lot),
                ),
                const SizedBox(height: 12),
                SegmentedButton<String>(
                  segments: [for (final e in severities.entries) ButtonSegment(value: e.key, label: Text(e.value))],
                  selected: {severity},
                  onSelectionChanged: (s) => setSheet(() => severity = s.first),
                ),
                const SizedBox(height: 12),
                TextField(controller: action, decoration: const InputDecoration(labelText: 'Travail à faire')),
                const SizedBox(height: 16),
                FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Enregistrer')),
              ],
            ),
          ),
        ),
      ),
    );
    if (ok != true) return;
    d
      ..description = description.text.trim()
      ..location = location.text.trim()
      ..action = action.text.trim()
      ..lot = lot
      ..severity = severity
      ..needsAi = false;
    await store.saveDefect(d);
  }

  Widget _photo(String caption, Photo? photo, {VoidCallback? onAdd}) => Expanded(
        child: Column(
          children: [
            AspectRatio(
              aspectRatio: 4 / 3,
              child: photo != null
                  ? SizedBox.expand(child: PhotoView(photo: photo, radius: 12))
                  : OutlinedButton(onPressed: onAdd, child: const Text('+ Photo')),
            ),
            const SizedBox(height: 4),
            Text(caption, style: const TextStyle(color: muted, fontSize: 13)),
          ],
        ),
      );

  Widget _line(String label, String value) => Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(width: 130, child: Text(label, style: const TextStyle(color: muted))),
            Expanded(child: Text(value)),
          ],
        ),
      );

  @override
  Widget build(BuildContext context) {
    return Live<_DefectData>(
      load: _load,
      builder: (context, data) {
        final d = data.defect;
        if (d == null || d.deleted) {
          return Scaffold(appBar: AppBar(), body: const Center(child: Text('Défaut introuvable.')));
        }
        final before = data.photos.where((p) => p.kind == 'photo_avant').toList();
        final after = data.photos.where((p) => p.kind == 'photo_apres').toList();
        // Seul, ou ingénieur dans une équipe : « corrigé » est définitif. Technicien d'équipe : à vérifier.
        final role = Api.session.value?.role ?? 'admin';
        final doneStatus = role == 'technicien' ? 'levee_declaree' : 'levee';
        final waiting = d.status == 'levee_declaree';

        return Scaffold(
          appBar: AppBar(
            title: Text(d.number > 0 ? 'Défaut n° ${d.number}' : 'Défaut', style: const TextStyle(fontWeight: FontWeight.w800)),
          ),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Align(alignment: Alignment.centerLeft, child: Chip2.status(d.status)),
              const SizedBox(height: 12),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _photo(
                    'Avant',
                    before.isNotEmpty ? before.first : null,
                    onAdd: () async {
                      final path = await _shoot();
                      if (path != null) await store.addPhoto(d.id, 'photo_avant', path);
                    },
                  ),
                  if (after.isNotEmpty) ...[const SizedBox(width: 10), _photo('Après', after.first)],
                ],
              ),
              const SizedBox(height: 14),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(d.description.isNotEmpty ? d.description : 'Sans description',
                          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                      const SizedBox(height: 6),
                      _line('Corps de métier', d.needsAi ? 'Classement en attente de connexion' : (lots[d.lot] ?? d.lot)),
                      if (d.location.isNotEmpty) _line('Lieu', d.location),
                      _line('Gravité', severities[d.severity] ?? d.severity),
                      if (d.action.isNotEmpty) _line('Travail à faire', d.action),
                      const SizedBox(height: 12),
                      OutlinedButton(onPressed: () => _edit(d), child: const Text('Modifier')),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              if (d.done)
                OutlinedButton(onPressed: () => _setStatus(d, 'ouverte'), child: const Text("Rouvrir : ce n'est pas corrigé"))
              else if (waiting && role == 'technicien')
                const Text("En attente de vérification par l'ingénieur.", style: TextStyle(color: muted))
              else if (waiting) ...[
                FilledButton.icon(
                  onPressed: () => _setStatus(d, 'levee'),
                  icon: const Icon(Icons.check),
                  label: const Text('Valider la correction'),
                ),
                const SizedBox(height: 10),
                OutlinedButton(onPressed: () => _setStatus(d, 'refusee'), child: const Text('Refuser : à reprendre')),
              ] else ...[
                FilledButton.icon(
                  onPressed: () => _markFixed(d, doneStatus),
                  icon: const Icon(Icons.check),
                  label: const Text("C'est corrigé : prendre la photo"),
                ),
                const SizedBox(height: 6),
                const Text('La photo « après » sert de preuve dans le rapport.', style: TextStyle(color: muted, fontSize: 13)),
              ],
              TextButton(
                onPressed: () => _delete(d),
                child: const Text('Supprimer ce défaut', style: TextStyle(color: warnRed)),
              ),
            ],
          ),
        );
      },
    );
  }
}
