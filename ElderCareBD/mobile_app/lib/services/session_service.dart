import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/caregiver_verification.dart';

class SessionService {
  static const String _caregiverIdKey = 'caregiver_id';
  static const String _caregiverNameKey = 'caregiver_name';
  static const String _authTokenKey = 'auth_token';
  static const String _pendingVerificationKey =
      'pending_caregiver_verification';

  static const String _selectedPatientIdKey = 'selected_patient_id';
  static const String _selectedPatientNameKey = 'selected_patient_name';

  static Future<void> saveCaregiverSession({
    required int caregiverId,
    required String caregiverName,
    required String authToken,
  }) async {
    final prefs = await SharedPreferences.getInstance();

    await prefs.setInt(_caregiverIdKey, caregiverId);
    await prefs.setString(_caregiverNameKey, caregiverName);
    await prefs.setString(_authTokenKey, authToken);
    await prefs.remove(_pendingVerificationKey);
    await prefs.remove(_selectedPatientIdKey);
    await prefs.remove(_selectedPatientNameKey);
  }

  static Future<int?> getCaregiverId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_caregiverIdKey);
  }

  static Future<String?> getCaregiverName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_caregiverNameKey);
  }

  static Future<String?> getAuthToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_authTokenKey);
  }

  static Future<void> savePendingVerification(
    PendingVerificationContext pending,
  ) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_caregiverIdKey);
    await prefs.remove(_caregiverNameKey);
    await prefs.remove(_authTokenKey);
    await prefs.remove(_selectedPatientIdKey);
    await prefs.remove(_selectedPatientNameKey);
    await prefs.setString(
      _pendingVerificationKey,
      jsonEncode(pending.toJson()),
    );
  }

  static Future<PendingVerificationContext?> getPendingVerification() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_pendingVerificationKey);
    if (raw == null || raw.trim().isEmpty) return null;

    try {
      final pending = PendingVerificationContext.tryParse(jsonDecode(raw));
      if (pending != null) return pending;
    } on FormatException {
      // Invalid local state is discarded below.
    }

    await prefs.remove(_pendingVerificationKey);
    return null;
  }

  static Future<void> clearPendingVerification() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_pendingVerificationKey);
  }

  static Future<void> saveSelectedPatient({
    required int patientId,
    required String patientName,
  }) async {
    final prefs = await SharedPreferences.getInstance();

    await prefs.setInt(_selectedPatientIdKey, patientId);
    await prefs.setString(_selectedPatientNameKey, patientName);
  }

  static Future<int?> getSelectedPatientId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_selectedPatientIdKey);
  }

  static Future<String?> getSelectedPatientName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_selectedPatientNameKey);
  }

  static Future<void> clearSession() async {
    final prefs = await SharedPreferences.getInstance();

    await prefs.remove(_caregiverIdKey);
    await prefs.remove(_caregiverNameKey);
    await prefs.remove(_authTokenKey);
    await prefs.remove(_pendingVerificationKey);
    await prefs.remove(_selectedPatientIdKey);
    await prefs.remove(_selectedPatientNameKey);
  }
}
