/// Données locales (SQLite) + synchronisation.
///
/// Tout ce que l'utilisateur fait est d'abord enregistré sur le téléphone, puis envoyé au serveur
/// dès qu'il y a du réseau. Les identifiants sont créés ici : renvoyer deux fois ne crée pas de doublon.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'models.dart';

const _uuid = Uuid();
String _now() => DateTime.now().toUtc().toIso8601String();

class ProjectSummary {
  ProjectSummary(this.project, this.total, this.done);
  final Project project;
  final int total;
  final int done;
}

/// Source unique des données pour les écrans. `notifyListeners` = quelque chose a changé, relisez.
class Store extends ChangeNotifier {
  Database? _db;
  String _owner = '';

  bool online = true;
  bool syncing = false;
  int pending = 0;
  String error = '';

  /// Limite de l'offre atteinte (stockage, nombre de rapports) : message à montrer avec le lien vers les offres.
  String limit = '';

  /// Une base par compte : deux personnes sur le même téléphone ne voient pas les rapports de l'autre.
  Future<Database> get db async {
    final owner = Api.session.value?.orgId ?? 'anonyme';
    if (_db != null && _owner == owner) return _db!;
    await _db?.close();
    _owner = owner;
    final dir = await getDatabasesPath();
    _db = await openDatabase(
      p.join(dir, 'reserva_$owner.db'),
      version: 1,
      onCreate: (d, _) async {
        await d.execute('CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT, client TEXT, location TEXT, '
            'created_at TEXT, dirty INTEGER, deleted INTEGER)');
        await d.execute('CREATE TABLE defects (id TEXT PRIMARY KEY, project_id TEXT, number INTEGER, location TEXT, '
            'lot TEXT, description TEXT, action TEXT, severity TEXT, status TEXT, transcript TEXT, updated_at TEXT, '
            'deleted INTEGER, dirty INTEGER, needs_ai INTEGER)');
        await d.execute('CREATE INDEX defects_project ON defects (project_id)');
        await d.execute('CREATE TABLE photos (id TEXT PRIMARY KEY, reserve_id TEXT, kind TEXT, path TEXT, uploaded INTEGER)');
        await d.execute('CREATE INDEX photos_reserve ON photos (reserve_id)');
      },
    );
    return _db!;
  }

  Future<void> _put(String table, Map<String, Object?> row) async =>
      (await db).insert(table, row, conflictAlgorithm: ConflictAlgorithm.replace);

  Future<Directory> _photoDir() async {
    await db; // fixe le compte courant
    final base = await getApplicationDocumentsDirectory();
    final dir = Directory(p.join(base.path, 'photos_$_owner'));
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return dir;
  }

  // ---------- lecture ----------

  Future<List<ProjectSummary>> listProjects() async {
    final d = await db;
    final projects = (await d.query('projects', where: 'deleted = 0', orderBy: 'created_at DESC')).map(Project.fromMap);
    final out = <ProjectSummary>[];
    for (final pr in projects) {
      final rows = await d.query('defects', columns: ['status'], where: 'project_id = ? AND deleted = 0', whereArgs: [pr.id]);
      out.add(ProjectSummary(pr, rows.length, rows.where((r) => r['status'] == 'levee').length));
    }
    return out;
  }

  Future<Project?> getProject(String id) async {
    final rows = await (await db).query('projects', where: 'id = ?', whereArgs: [id]);
    return rows.isEmpty ? null : Project.fromMap(rows.first);
  }

  Future<Defect?> getDefect(String id) async {
    final rows = await (await db).query('defects', where: 'id = ?', whereArgs: [id]);
    return rows.isEmpty ? null : Defect.fromMap(rows.first);
  }

  Future<List<Defect>> listDefects(String projectId) async {
    final rows = await (await db).query('defects', where: 'project_id = ? AND deleted = 0', whereArgs: [projectId]);
    final list = rows.map(Defect.fromMap).toList();
    list.sort((a, b) {
      final na = a.number == 0 ? 1 << 30 : a.number;
      final nb = b.number == 0 ? 1 << 30 : b.number;
      return na != nb ? na.compareTo(nb) : a.updatedAt.compareTo(b.updatedAt);
    });
    return list;
  }

  Future<List<Photo>> listPhotos(String defectId) async {
    final rows = await (await db).query('photos', where: 'reserve_id = ?', whereArgs: [defectId]);
    return rows.map(Photo.fromMap).toList();
  }

  // ---------- écriture (toujours locale d'abord) ----------

  Future<Project> createProject(String name, {String client = ''}) async {
    final pr = Project(id: _uuid.v4(), name: name, client: client, createdAt: _now(), dirty: true);
    await _put('projects', pr.toMap());
    notifyListeners();
    unawaited(sync());
    return pr;
  }

  /// Supprime un rapport, ses défauts et ses photos. La place est rendue au compte.
  Future<void> deleteProject(String id) async {
    final pr = await getProject(id);
    if (pr == null) return;
    pr
      ..deleted = true
      ..dirty = true;
    await _put('projects', pr.toMap());
    notifyListeners();
    unawaited(sync());
  }

  Defect newDefect(String projectId) => Defect(id: _uuid.v4(), projectId: projectId, updatedAt: _now());

  Future<void> saveDefect(Defect d) async {
    d
      ..updatedAt = _now()
      ..dirty = true;
    await _put('defects', d.toMap());
    notifyListeners();
    unawaited(sync());
  }

  /// Garde une copie de la photo dans l'application (déjà réduite à 1600 px par l'appareil photo).
  Future<void> addPhoto(String defectId, String kind, String sourcePath) async {
    final id = _uuid.v4();
    final target = p.join((await _photoDir()).path, '$id.jpg');
    await File(sourcePath).copy(target);
    await _put('photos', Photo(id: id, reserveId: defectId, kind: kind, path: target).toMap());
    notifyListeners();
    unawaited(sync());
  }

  /// Fichier affichable. Les photos prises sur un autre appareil sont téléchargées une fois puis gardées.
  Future<File?> photoFile(Photo photo) async {
    if (photo.path != null && File(photo.path!).existsSync()) return File(photo.path!);
    try {
      final bytes = await Api.download('/media/${photo.id}');
      final file = File(p.join((await _photoDir()).path, '${photo.id}.jpg'));
      await file.writeAsBytes(bytes);
      photo.path = file.path;
      await _put('photos', photo.toMap());
      return file;
    } on ApiException {
      return null;
    }
  }

  Future<void> _dropLocalProject(String id) async {
    final d = await db;
    for (final row in await d.query('defects', columns: ['id'], where: 'project_id = ?', whereArgs: [id])) {
      await _dropLocalDefect(row['id'] as String);
    }
    await d.delete('projects', where: 'id = ?', whereArgs: [id]);
  }

  Future<void> _dropLocalDefect(String id) async {
    final d = await db;
    for (final ph in await listPhotos(id)) {
      if (ph.path != null) {
        final f = File(ph.path!);
        if (f.existsSync()) f.deleteSync();
      }
    }
    await d.delete('photos', where: 'reserve_id = ?', whereArgs: [id]);
    await d.delete('defects', where: 'id = ?', whereArgs: [id]);
  }

  // ---------- synchronisation ----------

  Future<int> _countPending() async {
    final d = await db;
    final a = Sqflite.firstIntValue(await d.rawQuery('SELECT COUNT(*) FROM projects WHERE dirty = 1')) ?? 0;
    final b = Sqflite.firstIntValue(await d.rawQuery('SELECT COUNT(*) FROM defects WHERE dirty = 1')) ?? 0;
    final c = Sqflite.firstIntValue(await d.rawQuery('SELECT COUNT(*) FROM photos WHERE uploaded = 0')) ?? 0;
    return a + b + c;
  }

  Future<void>? _running;
  bool _again = false;

  /// Envoie ce qui attend, puis récupère ce qui a changé. Sans réseau, ne fait rien : on réessaiera.
  Future<void> sync() {
    if (_running != null) {
      _again = true;
      return _running!;
    }
    final run = _doSync().whenComplete(() {
      _running = null;
      if (_again) {
        _again = false;
        unawaited(sync());
      }
    });
    _running = run;
    return run;
  }

  Future<void> _doSync() async {
    if (Api.session.value == null) return;
    syncing = true;
    error = '';
    limit = '';
    notifyListeners();
    try {
      await _push();
      await _pull();
      online = true;
    } on ApiException catch (e) {
      online = !e.offline;
      if (!e.offline) error = e.message;
    } catch (e) {
      error = 'Synchronisation interrompue';
      debugPrint('sync: $e');
    } finally {
      syncing = false;
      if (Api.session.value != null) pending = await _countPending();
      notifyListeners();
    }
  }

  Future<void> _push() async {
    final d = await db;

    final waiting = <String>{}; // rapports pas encore acceptés par le serveur
    for (final row in await d.query('projects', where: 'dirty = 1')) {
      final pr = Project.fromMap(row);
      try {
        if (pr.deleted) {
          await Api.request('DELETE', '/projects/${pr.id}');
          await _dropLocalProject(pr.id);
          continue;
        }
        await Api.post('/projects', {'id': pr.id, 'name': pr.name, 'client': pr.client, 'location': pr.location});
        pr.dirty = false;
        await _put('projects', pr.toMap());
      } on ApiException catch (e) {
        // Limite de l'offre : le rapport reste sur le téléphone, rien n'est perdu, on le signale.
        if (e.status != 402) rethrow;
        waiting.add(pr.id);
        limit = e.message;
      }
    }

    final dirty = (await d.query('defects', where: 'dirty = 1'))
        .map(Defect.fromMap)
        .where((x) => !waiting.contains(x.projectId))
        .toList();

    // Aide IA : la note est classée (lot, lieu, gravité, travail à faire) avant l'envoi.
    for (final x in dirty.where((x) => x.needsAi && x.transcript.trim().isNotEmpty && !x.deleted)) {
      try {
        final res = await Api.post('/ai/structure', {'text': x.transcript}) as Map<String, dynamic>;
        final draft = res['draft'] as Map<String, dynamic>;
        x
          ..lot = (draft['lot'] ?? x.lot) as String
          ..severity = (draft['severity'] ?? x.severity) as String
          ..location = x.location.isNotEmpty ? x.location : (draft['location'] ?? '') as String
          ..action = x.action.isNotEmpty ? x.action : (draft['action'] ?? '') as String
          ..description = ((draft['description'] ?? '') as String).isNotEmpty ? draft['description'] as String : x.description
          ..needsAi = false;
        await _put('defects', x.toMap());
      } on ApiException catch (e) {
        if (e.offline) rethrow; // réseau coupé : on réessaiera tout
        x.needsAi = false; // l'IA n'a pas pu aider : la note part telle quelle, modifiable à la main
      }
    }

    if (dirty.isNotEmpty) {
      final res = await Api.post('/sync/push', {'reserves': dirty.map((x) => x.toServer()).toList()}) as Map<String, dynamic>;
      for (final r in (res['results'] as List).cast<Map<String, dynamic>>()) {
        final x = dirty.firstWhere((e) => e.id == r['id']);
        if (r['result'] == 'rejected') error = (r['detail'] ?? 'Une modification a été refusée').toString();
        // Modifié pendant l'envoi : on garde la version la plus récente, elle partira au prochain passage.
        final current = await getDefect(x.id);
        if (current != null && current.updatedAt != x.updatedAt) {
          current.number = (r['number'] ?? current.number) as int;
          await _put('defects', current.toMap());
          _again = true;
          continue;
        }
        if (x.deleted && r['result'] != 'rejected') {
          await _dropLocalDefect(x.id);
        } else {
          x
            ..number = (r['number'] ?? x.number) as int
            ..dirty = false;
          await _put('defects', x.toMap());
        }
      }
    }

    for (final row in await d.query('photos', where: 'uploaded = 0 AND path IS NOT NULL')) {
      final ph = Photo.fromMap(row);
      final file = File(ph.path!);
      if (!file.existsSync()) {
        await d.delete('photos', where: 'id = ?', whereArgs: [ph.id]);
        continue;
      }
      try {
        await Api.uploadPhoto(ph.id, ph.reserveId, ph.kind, file);
        ph.uploaded = true;
        await _put('photos', ph.toMap());
      } on ApiException catch (e) {
        if (e.status == 404) {
          await d.delete('photos', where: 'id = ?', whereArgs: [ph.id]); // défaut supprimé entre-temps
        } else if (e.status == 402) {
          limit = e.message; // stockage plein : les photos restent sur le téléphone
          break;
        } else {
          rethrow;
        }
      }
    }
  }

  Future<void> _pull() async {
    final d = await db;
    final me = await Api.get('/me') as Map<String, dynamic>;
    final s = Api.session.value;
    if (s != null) {
      await Api.setSession(Session(s.token, Map<String, dynamic>.from(me['user'] as Map), Map<String, dynamic>.from(me['org'] as Map)));
    }

    final remote = ((await Api.get('/projects')) as List).cast<Map<String, dynamic>>();
    final remoteIds = remote.map((r) => r['id'] as String).toSet();
    final local = (await d.query('projects')).map(Project.fromMap).toList();
    for (final pr in local) {
      if (!pr.dirty && !remoteIds.contains(pr.id)) await _dropLocalProject(pr.id);
    }
    for (final r in remote) {
      final id = r['id'] as String;
      final mine = local.where((x) => x.id == id);
      if (mine.isNotEmpty && mine.first.deleted) continue; // suppression en attente d'envoi
      await _put(
        'projects',
        Project(id: id, name: (r['name'] ?? '') as String, client: (r['client'] ?? '') as String,
                location: (r['location'] ?? '') as String, createdAt: (r['created_at'] ?? '') as String).toMap(),
      );

      final server = ((await Api.get('/projects/$id/reserves')) as List).cast<Map<String, dynamic>>();
      final serverIds = server.map((x) => x['id'] as String).toSet();
      final localDefects = (await d.query('defects', where: 'project_id = ?', whereArgs: [id])).map(Defect.fromMap).toList();
      for (final x in localDefects) {
        if (!x.dirty && !serverIds.contains(x.id)) await _dropLocalDefect(x.id);
      }
      final dirtyIds = localDefects.where((x) => x.dirty).map((x) => x.id).toSet();
      for (final x in server) {
        if (!dirtyIds.contains(x['id'])) {
          await _put('defects', Defect.fromMap({...x, 'deleted': 0, 'dirty': 0, 'needs_ai': 0}).toMap());
        }
        for (final m in ((x['media'] ?? []) as List).cast<Map<String, dynamic>>()) {
          final kind = m['kind'] as String;
          if (kind != 'photo_avant' && kind != 'photo_apres') continue;
          final known = await d.query('photos', columns: ['id'], where: 'id = ?', whereArgs: [m['id']]);
          if (known.isEmpty) {
            await _put('photos', Photo(id: m['id'] as String, reserveId: m['reserve_id'] as String, kind: kind, uploaded: true).toMap());
          }
        }
      }
    }
  }

  Future<void> logout() async {
    await _db?.close();
    _db = null;
    _owner = '';
    pending = 0;
    error = '';
    limit = '';
    await Api.setSession(null);
    notifyListeners();
  }
}

final Store store = Store();
