/// Modèles de données, identiques à ceux du serveur et de l'application web.
library;

int _b(bool v) => v ? 1 : 0;
bool _t(Object? v) => v == 1 || v == true;

/// Un rapport = un chantier. `dirty` : pas encore envoyé au serveur.
class Project {
  Project({
    required this.id,
    required this.name,
    this.client = '',
    this.location = '',
    required this.createdAt,
    this.dirty = false,
    this.deleted = false,
  });

  final String id;
  String name;
  String client;
  String location;
  String createdAt;
  bool dirty;
  bool deleted;

  factory Project.fromMap(Map<String, Object?> m) => Project(
        id: m['id'] as String,
        name: (m['name'] ?? '') as String,
        client: (m['client'] ?? '') as String,
        location: (m['location'] ?? '') as String,
        createdAt: (m['created_at'] ?? '') as String,
        dirty: _t(m['dirty']),
        deleted: _t(m['deleted']),
      );

  Map<String, Object?> toMap() => {
        'id': id,
        'name': name,
        'client': client,
        'location': location,
        'created_at': createdAt,
        'dirty': _b(dirty),
        'deleted': _b(deleted),
      };
}

/// Un défaut constaté (une « réserve » dans le rapport PDF).
class Defect {
  Defect({
    required this.id,
    required this.projectId,
    this.number = 0,
    this.location = '',
    this.lot = 'autre',
    this.description = '',
    this.action = '',
    this.severity = 'mineure',
    this.status = 'ouverte',
    this.transcript = '',
    required this.updatedAt,
    this.deleted = false,
    this.dirty = false,
    this.needsAi = false,
  });

  final String id;
  final String projectId;
  int number; // 0 tant que le serveur ne l'a pas numéroté
  String location;
  String lot;
  String description;
  String action;
  String severity;
  String status;
  String transcript;
  String updatedAt;
  bool deleted;
  bool dirty;

  /// La note attend d'être classée par l'IA à la prochaine connexion.
  bool needsAi;

  bool get done => status == 'levee';

  factory Defect.fromMap(Map<String, Object?> m) => Defect(
        id: m['id'] as String,
        projectId: m['project_id'] as String,
        number: (m['number'] ?? 0) as int,
        location: (m['location'] ?? '') as String,
        lot: (m['lot'] ?? 'autre') as String,
        description: (m['description'] ?? '') as String,
        action: (m['action'] ?? '') as String,
        severity: (m['severity'] ?? 'mineure') as String,
        status: (m['status'] ?? 'ouverte') as String,
        transcript: (m['transcript'] ?? '') as String,
        updatedAt: (m['updated_at'] ?? '') as String,
        deleted: _t(m['deleted']),
        dirty: _t(m['dirty']),
        needsAi: _t(m['needs_ai']),
      );

  Map<String, Object?> toMap() => {
        'id': id,
        'project_id': projectId,
        'number': number,
        'location': location,
        'lot': lot,
        'description': description,
        'action': action,
        'severity': severity,
        'status': status,
        'transcript': transcript,
        'updated_at': updatedAt,
        'deleted': _b(deleted),
        'dirty': _b(dirty),
        'needs_ai': _b(needsAi),
      };

  /// Ce qui part au serveur.
  Map<String, Object?> toServer() => {
        'id': id,
        'project_id': projectId,
        'location': location,
        'lot': lot,
        'description': description,
        'action': action,
        'severity': severity,
        'status': status,
        'transcript': transcript,
        'updated_at': updatedAt,
        'deleted': deleted,
      };
}

class Photo {
  Photo({required this.id, required this.reserveId, required this.kind, this.path, this.uploaded = false});

  final String id;
  final String reserveId;
  final String kind; // photo_avant | photo_apres
  String? path; // fichier local ; absent tant qu'une photo d'un autre appareil n'est pas téléchargée
  bool uploaded;

  factory Photo.fromMap(Map<String, Object?> m) => Photo(
        id: m['id'] as String,
        reserveId: m['reserve_id'] as String,
        kind: m['kind'] as String,
        path: m['path'] as String?,
        uploaded: _t(m['uploaded']),
      );

  Map<String, Object?> toMap() =>
      {'id': id, 'reserve_id': reserveId, 'kind': kind, 'path': path, 'uploaded': _b(uploaded)};
}

const Map<String, String> lots = {
  'gros_oeuvre': 'Gros œuvre',
  'maconnerie': 'Maçonnerie / enduits',
  'etancheite': 'Étanchéité / toiture',
  'menuiserie_bois': 'Menuiserie bois',
  'menuiserie_alu': 'Menuiserie alu / vitrerie',
  'ferronnerie': 'Ferronnerie',
  'plomberie': 'Plomberie',
  'electricite': 'Électricité',
  'carrelage': 'Carrelage',
  'peinture': 'Peinture',
  'faux_plafond': 'Faux plafond',
  'climatisation': 'Climatisation',
  'vrd': 'Extérieurs / VRD',
  'nettoyage': 'Nettoyage',
  'autre': 'Autre',
};

const Map<String, String> severities = {'mineure': 'Mineur', 'majeure': 'Important', 'bloquante': 'Urgent'};

// Mots simples à l'écran ; le PDF garde le vocabulaire officiel (réserve, levée).
const Map<String, String> statusLabels = {
  'ouverte': 'À corriger',
  'levee_declaree': 'Corrigé, à vérifier',
  'levee': 'Corrigé',
  'refusee': 'À reprendre',
};

/// 12500 -> « 12 500 FCFA »
String fcfa(num value) {
  final digits = value.round().abs().toString();
  final out = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) out.write(' ');
    out.write(digits[i]);
  }
  return '${value < 0 ? '-' : ''}$out FCFA';
}

String bytesLabel(num n) {
  const mb = 1024 * 1024;
  if (n >= 1024 * mb) return '${(n / (1024 * mb)).toStringAsFixed(1).replaceAll('.', ',')} Go';
  return '${(n / mb).toStringAsFixed(n < 10 * mb ? 1 : 0).replaceAll('.', ',')} Mo';
}
