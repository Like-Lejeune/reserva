/// Accès au serveur et session.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Adresse du serveur. À fournir à la compilation :
///   flutter run --dart-define=API_URL=https://votre-domaine.com
/// Par défaut : le serveur local vu depuis l'émulateur Android.
const String apiUrl = String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000');

class ApiException implements Exception {
  ApiException(this.status, this.message);

  /// 0 = pas de connexion ; 402 = limite de l'offre atteinte ; sinon le code HTTP.
  final int status;
  final String message;

  bool get offline => status == 0;

  @override
  String toString() => message;
}

class Session {
  Session(this.token, this.user, this.org);

  final String token;
  final Map<String, dynamic> user;
  final Map<String, dynamic> org;

  String get name => (user['name'] ?? '') as String;
  String get login => (user['login'] ?? '') as String;
  String get role => (user['role'] ?? 'admin') as String;
  String get orgId => (org['id'] ?? '') as String;
  String get planLabel => (org['plan_label'] ?? 'Gratuit') as String;

  factory Session.fromJson(Map<String, dynamic> j) => Session(
        j['token'] as String,
        Map<String, dynamic>.from(j['user'] as Map),
        Map<String, dynamic>.from(j['org'] as Map),
      );

  Map<String, dynamic> toJson() => {'token': token, 'user': user, 'org': org};
}

class Api {
  static const _key = 'reserva.session';

  /// La session est gardée sur le téléphone : l'application s'ouvre même sans réseau.
  static final ValueNotifier<Session?> session = ValueNotifier<Session?>(null);

  static Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null) return;
    try {
      session.value = Session.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      await prefs.remove(_key);
    }
  }

  static Future<void> setSession(Session? s) async {
    final prefs = await SharedPreferences.getInstance();
    if (s == null) {
      await prefs.remove(_key);
    } else {
      await prefs.setString(_key, jsonEncode(s.toJson()));
    }
    session.value = s;
  }

  static Map<String, String> _headers({bool json = false}) {
    final token = session.value?.token;
    return {
      if (token != null) 'Authorization': 'Bearer $token',
      if (json) 'Content-Type': 'application/json',
    };
  }

  static Uri _uri(String path) => Uri.parse('$apiUrl/api$path');

  static Future<T> _guard<T>(Future<T> Function() run) async {
    try {
      return await run().timeout(const Duration(seconds: 45));
    } on ApiException {
      rethrow;
    } on SocketException {
      throw ApiException(0, 'Pas de connexion');
    } on TimeoutException {
      throw ApiException(0, 'Pas de connexion');
    } on http.ClientException {
      throw ApiException(0, 'Pas de connexion');
    }
  }

  static Future<void> _check(http.Response res) async {
    if (res.statusCode >= 200 && res.statusCode < 300) return;
    if (res.statusCode == 401 && session.value != null) await setSession(null); // session expirée
    var detail = 'Erreur ${res.statusCode}';
    try {
      final body = jsonDecode(utf8.decode(res.bodyBytes));
      final d = (body as Map)['detail'];
      if (d is String) {
        detail = d;
      } else if (d is List && d.isNotEmpty && d.first is Map && (d.first as Map)['msg'] != null) {
        detail = (d.first as Map)['msg'].toString().replaceFirst('Value error, ', '');
      }
    } catch (_) {
      // réponse non JSON
    }
    throw ApiException(res.statusCode, detail);
  }

  /// Requête JSON. `body` absent = pas de corps.
  static Future<dynamic> request(String method, String path, {Object? body}) => _guard(() async {
        final req = http.Request(method, _uri(path))..headers.addAll(_headers(json: body != null));
        if (body != null) req.body = jsonEncode(body);
        final res = await http.Response.fromStream(await req.send());
        await _check(res);
        return res.bodyBytes.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
      });

  static Future<dynamic> get(String path) => request('GET', path);
  static Future<dynamic> post(String path, [Object? body]) => request('POST', path, body: body);

  /// Envoi d'une photo. Rejouable : le serveur reconnaît l'identifiant déjà reçu.
  static Future<void> uploadPhoto(String mediaId, String reserveId, String kind, File file) => _guard(() async {
        final req = http.MultipartRequest('PUT', _uri('/media/$mediaId'))
          ..headers.addAll(_headers())
          ..fields['reserve_id'] = reserveId
          ..fields['kind'] = kind
          ..files.add(await http.MultipartFile.fromPath('file', file.path, filename: '$mediaId.jpg'));
        await _check(await http.Response.fromStream(await req.send()));
      });

  static Future<List<int>> download(String path) => _guard(() async {
        final res = await http.get(_uri(path), headers: _headers());
        await _check(res);
        return res.bodyBytes;
      });
}
