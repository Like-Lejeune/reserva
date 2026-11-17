/// Petits composants partagés par les écrans.
library;

import 'dart:io';

import 'package:flutter/material.dart';

import 'models.dart';
import 'store.dart';

const brand = Color(0xFF1F3A5F);
const accent = Color(0xFFF4C26B);
const okGreen = Color(0xFF2E7D32);
const warnRed = Color(0xFFB3261E);
const muted = Color(0xFF64707F);

/// Relit `load` à chaque changement des données locales, puis reconstruit.
class Live<T> extends StatefulWidget {
  const Live({super.key, required this.load, required this.builder});

  final Future<T> Function() load;
  final Widget Function(BuildContext context, T value) builder;

  @override
  State<Live<T>> createState() => _LiveState<T>();
}

class _LiveState<T> extends State<Live<T>> {
  T? _value;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    store.addListener(_refresh);
    _refresh();
  }

  @override
  void dispose() {
    store.removeListener(_refresh);
    super.dispose();
  }

  Future<void> _refresh() async {
    final value = await widget.load();
    if (!mounted) return;
    setState(() {
      _value = value;
      _ready = true;
    });
  }

  @override
  Widget build(BuildContext context) =>
      _ready ? widget.builder(context, _value as T) : const Center(child: CircularProgressIndicator());
}

/// Bandeau d'état : hors connexion, envoi en cours, limite de l'offre, erreur.
class SyncBanner extends StatelessWidget {
  const SyncBanner({super.key, this.onSeePlans});

  final VoidCallback? onSeePlans;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: store,
      builder: (context, _) {
        String? text;
        var color = const Color(0xFF2B3A4D);
        if (store.limit.isNotEmpty) {
          text = store.limit;
          color = warnRed;
        } else if (store.error.isNotEmpty) {
          text = store.error;
          color = warnRed;
        } else if (!store.online) {
          text = store.pending > 0
              ? 'Hors connexion, ${store.pending} élément(s) seront envoyés au retour du réseau'
              : 'Hors connexion, vous pouvez continuer';
        } else if (store.syncing && store.pending > 0) {
          text = 'Envoi en cours…';
        }
        if (text == null) return const SizedBox.shrink();
        return Material(
          color: color,
          child: InkWell(
            onTap: store.limit.isNotEmpty ? onSeePlans : null,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              child: Text(
                store.limit.isNotEmpty && onSeePlans != null ? '$text Touchez pour voir les offres.' : text,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white, fontSize: 13),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// Affiche une photo locale, ou la télécharge une fois si elle vient d'un autre appareil.
class PhotoView extends StatelessWidget {
  const PhotoView({super.key, required this.photo, this.size, this.radius = 10});

  final Photo? photo;
  final double? size;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final placeholder = Container(
      width: size,
      height: size,
      color: const Color(0xFFE9ECF0),
      alignment: Alignment.center,
      child: const Icon(Icons.photo_camera_outlined, color: muted),
    );
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: photo == null
          ? placeholder
          : FutureBuilder<File?>(
              key: ValueKey('${photo!.id}:${photo!.path}'),
              future: store.photoFile(photo!),
              builder: (context, snap) => snap.data == null
                  ? placeholder
                  : Image.file(snap.data!, width: size, height: size, fit: BoxFit.cover),
            ),
    );
  }
}

class Chip2 extends StatelessWidget {
  const Chip2(this.label, {super.key, this.background = const Color(0xFFE9ECF0), this.color = const Color(0xFF16202E)});

  final String label;
  final Color background;
  final Color color;

  factory Chip2.status(String status) {
    switch (status) {
      case 'levee':
        return Chip2(statusLabels[status]!, background: const Color(0xFFE3F3E4), color: okGreen);
      case 'levee_declaree':
        return Chip2(statusLabels[status]!, background: const Color(0xFFFFF4DC), color: const Color(0xFF8A5A00));
      default:
        return Chip2(statusLabels[status] ?? status, background: const Color(0xFFFDECEA), color: warnRed);
    }
  }

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(20)),
        child: Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: color)),
      );
}

/// Une jauge : ce qui est utilisé, sur ce qui est permis. Orange à 80 %, rouge à 100 %.
class Meter extends StatelessWidget {
  const Meter({super.key, required this.label, required this.used, required this.limit, this.format});

  final String label;
  final num used;
  final num? limit; // null = illimité
  final String Function(num)? format;

  @override
  Widget build(BuildContext context) {
    final f = format ?? (num n) => n.round().toString();
    final ratio = limit == null || limit == 0 ? 0.0 : (used / limit!).clamp(0.0, 1.0).toDouble();
    final color = ratio >= 1 ? warnRed : (ratio >= 0.8 ? const Color(0xFFC98A1A) : okGreen);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label),
            Text(limit == null ? f(used) : '${f(used)} sur ${f(limit!)}', style: const TextStyle(fontWeight: FontWeight.w700)),
          ],
        ),
        const SizedBox(height: 6),
        if (limit == null)
          const Text('Illimité', style: TextStyle(color: muted, fontSize: 13))
        else
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(value: ratio, minHeight: 8, color: color, backgroundColor: const Color(0xFFE3E7EC)),
          ),
        if (ratio >= 1) const Text('Limite atteinte', style: TextStyle(color: warnRed, fontSize: 13)),
      ],
    );
  }
}
