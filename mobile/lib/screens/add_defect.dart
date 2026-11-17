import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../store.dart';
import '../widgets.dart';

/// Ajouter un défaut : une photo, une phrase (dictée ou tapée), Enregistrer.
/// Le lot, le lieu, la gravité et le travail à faire sont remplis par l'IA à l'envoi ; tout reste modifiable.
class AddDefectScreen extends StatefulWidget {
  const AddDefectScreen({super.key, required this.projectId});

  final String projectId;

  @override
  State<AddDefectScreen> createState() => _AddDefectScreenState();
}

class _AddDefectScreenState extends State<AddDefectScreen> {
  final _note = TextEditingController();
  final _picker = ImagePicker();
  final _speech = SpeechToText();
  String? _photoPath;
  bool _listening = false;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _note.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _speech.stop();
    _note.dispose();
    super.dispose();
  }

  Future<void> _takePhoto() async {
    // Réduite à la prise de vue : moins de mémoire, moins de données mobiles.
    final shot = await _picker.pickImage(source: ImageSource.camera, maxWidth: 1600, maxHeight: 1600, imageQuality: 80);
    if (shot != null && mounted) setState(() => _photoPath = shot.path);
  }

  /// Dictée gratuite : la reconnaissance vocale du téléphone, en français.
  Future<void> _toggleMic() async {
    if (_listening) {
      await _speech.stop();
      if (mounted) setState(() => _listening = false);
      return;
    }
    final available = await _speech.initialize(
      onStatus: (status) {
        if ((status == 'done' || status == 'notListening') && mounted) setState(() => _listening = false);
      },
      onError: (_) {
        if (mounted) setState(() => _listening = false);
      },
    );
    if (!available) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text("La dictée n'est pas disponible sur ce téléphone. Tapez la note.")));
      }
      return;
    }
    setState(() => _listening = true);
    await _speech.listen(
      localeId: 'fr_FR',
      onResult: (result) {
        if (!result.finalResult) return;
        final words = result.recognizedWords.trim();
        if (words.isEmpty) return;
        _note.text = _note.text.isEmpty ? words : '${_note.text} $words';
      },
    );
  }

  Future<void> _save({required bool another}) async {
    final note = _note.text.trim();
    if (_photoPath == null && note.isEmpty) return;
    setState(() => _saving = true);
    await _speech.stop();
    final d = store.newDefect(widget.projectId)
      ..transcript = note
      ..description = note
      ..needsAi = note.isNotEmpty;
    await store.saveDefect(d);
    if (_photoPath != null) await store.addPhoto(d.id, 'photo_avant', _photoPath!);
    if (!mounted) return;
    if (another) {
      setState(() {
        _photoPath = null;
        _note.clear();
        _saving = false;
        _listening = false;
      });
    } else {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final empty = _photoPath == null && _note.text.trim().isEmpty;
    return Scaffold(
      appBar: AppBar(title: const Text('Nouveau défaut', style: TextStyle(fontWeight: FontWeight.w800))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          AspectRatio(
            aspectRatio: 4 / 3,
            child: Material(
              color: Colors.white,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
                side: const BorderSide(color: Color(0xFFB9C1CC), width: 2),
              ),
              clipBehavior: Clip.antiAlias,
              child: InkWell(
                onTap: _takePhoto,
                child: _photoPath == null
                    ? const Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.photo_camera_outlined, size: 44, color: brand),
                          SizedBox(height: 8),
                          Text('Prendre la photo', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: brand)),
                        ],
                      )
                    : Image.file(File(_photoPath!), fit: BoxFit.cover),
              ),
            ),
          ),
          const SizedBox(height: 16),
          const Text("Qu'est-ce qui ne va pas ?", style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          TextField(
            controller: _note,
            minLines: 3,
            maxLines: 5,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(hintText: "Ex. Fuite sous l'évier de la cuisine"),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: _toggleMic,
            style: _listening ? OutlinedButton.styleFrom(backgroundColor: warnRed, foregroundColor: Colors.white) : null,
            icon: Icon(_listening ? Icons.stop : Icons.mic_none),
            label: Text(_listening ? 'Arrêter la dictée' : 'Dicter'),
          ),
          const SizedBox(height: 8),
          const Text(
            'Le corps de métier, le lieu et la gravité sont remplis automatiquement. Vous pourrez les corriger.',
            style: TextStyle(color: muted, fontSize: 13),
          ),
          const SizedBox(height: 16),
          FilledButton(onPressed: empty || _saving ? null : () => _save(another: false), child: const Text('Enregistrer')),
          const SizedBox(height: 10),
          OutlinedButton(
            onPressed: empty || _saving ? null : () => _save(another: true),
            child: const Text('Enregistrer et ajouter un autre'),
          ),
        ],
      ),
    );
  }
}
