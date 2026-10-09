import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../models/caregiver_verification.dart';
import '../models/daily_observation.dart';
import '../models/model_prediction.dart';
import '../models/prescription_extraction.dart';
import 'session_service.dart';

class ApiException implements Exception {
  final String message;
  final int? statusCode;

  const ApiException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

class VerificationApiException extends ApiException {
  const VerificationApiException(
    super.message, {
    required this.code,
    this.pendingVerification,
    this.attemptsRemaining,
    this.retryAfterSeconds,
  });

  final String code;
  final PendingVerificationContext? pendingVerification;
  final int? attemptsRemaining;
  final int? retryAfterSeconds;
}

class ApiService {
  static const String _defaultBaseUrl = 'http://127.0.0.1:8000';
  static const String _configuredBaseUrl = String.fromEnvironment(
    'ELDERCARE_API_BASE_URL',
    defaultValue: _defaultBaseUrl,
  );
  static const Duration _requestTimeout = Duration(seconds: 15);
  static const Duration _ocrRequestTimeout = Duration(seconds: 35);

  /// Override with `--dart-define=ELDERCARE_API_BASE_URL=https://api.example`.
  ///
  /// The loopback default is suitable for a browser or desktop backend running
  /// on the same computer. Android devices and emulators must be given an
  /// address that can reach the backend host.
  static String get baseUrl {
    final configured = _configuredBaseUrl.trim();
    final value = configured.isEmpty ? _defaultBaseUrl : configured;
    return value.replaceFirst(RegExp(r'/+$'), '');
  }

  static Future<Map<String, dynamic>> _postJson(
    String path,
    Map<String, Object?> payload, {
    bool authenticated = false,
    bool requireAuthentication = false,
  }) async {
    final headers = await _headers(
      authenticated: authenticated,
      requireAuthentication: requireAuthentication,
    );
    final response = await _runRequest(
      () => http.post(
        Uri.parse('$baseUrl$path'),
        headers: headers,
        body: jsonEncode(payload),
      ),
    );

    return {
      'statusCode': response.statusCode,
      'body': decodeResponseObject(response.body),
    };
  }

  static Future<Map<String, dynamic>> _patchJson(
    String path,
    Map<String, Object?> payload, {
    bool authenticated = false,
    bool requireAuthentication = false,
  }) async {
    final headers = await _headers(
      authenticated: authenticated,
      requireAuthentication: requireAuthentication,
    );
    final response = await _runRequest(
      () => http.patch(
        Uri.parse('$baseUrl$path'),
        headers: headers,
        body: jsonEncode(payload),
      ),
    );
    return {
      'statusCode': response.statusCode,
      'body': decodeResponseObject(response.body),
    };
  }

  static Future<Map<String, String>> _headers({
    bool authenticated = false,
    bool includeJsonContentType = true,
    bool requireAuthentication = false,
  }) async {
    final headers = <String, String>{};
    if (includeJsonContentType) {
      headers['Content-Type'] = 'application/json';
    }
    if (!authenticated) return headers;

    final token = await SessionService.getAuthToken();
    if (token != null && token.trim().isNotEmpty) {
      headers['Authorization'] = 'Bearer ${token.trim()}';
    } else if (requireAuthentication) {
      throw const ApiException(
        'Your session has expired. Please sign in again.',
      );
    }
    return headers;
  }

  static Future<T> _runRequest<T>(
    Future<T> Function() request, {
    Duration timeout = _requestTimeout,
  }) async {
    try {
      return await request().timeout(timeout);
    } on TimeoutException {
      throw const ApiException(
        'The server took too long to respond. Please try again.',
      );
    } on http.ClientException {
      throw const ApiException(
        'Could not connect to the server. Please try again.',
      );
    } on Exception {
      throw const ApiException(
        'Could not connect to the server. Please try again.',
      );
    }
  }

  static Future<http.Response> _getAuthenticated(String path) async {
    final headers = await _headers(
      authenticated: true,
      includeJsonContentType: false,
      requireAuthentication: true,
    );
    return _runRequest(
      () => http.get(Uri.parse('$baseUrl$path'), headers: headers),
    );
  }

  static List<dynamic> _decodeResponseList(String responseBody) {
    if (responseBody.trim().isEmpty) {
      throw const ApiException('The server returned an empty response.');
    }

    try {
      final decoded = jsonDecode(responseBody);
      if (decoded is List) return decoded;
    } on FormatException {
      // The caller receives a stable user-facing error below.
    }

    throw const ApiException('The server returned an invalid response.');
  }

  static Never _throwResponseError(
    http.Response response, {
    required String fallback,
  }) {
    throw ApiException(
      errorMessage({
        'statusCode': response.statusCode,
        'body': decodeResponseObject(response.body),
      }, fallback: fallback),
      statusCode: response.statusCode,
    );
  }

  static Map<String, dynamic> decodeResponseObject(String responseBody) {
    if (responseBody.trim().isEmpty) {
      return {'detail': 'The server returned an empty response.'};
    }

    try {
      final decoded = jsonDecode(responseBody);
      if (decoded is Map<String, dynamic>) return decoded;
      if (decoded is Map) {
        return decoded.map((key, value) => MapEntry(key.toString(), value));
      }
    } on FormatException {
      // The caller receives a stable user-facing error below.
    }

    return {'detail': 'The server returned an invalid response.'};
  }

  static String errorMessage(
    Map<String, dynamic> result, {
    required String fallback,
  }) {
    final body = result['body'];
    if (body is Map) {
      final detail = body['detail'];
      if (detail is String && detail.trim().isNotEmpty) return detail;
      if (detail is List) {
        final messages = detail
            .map((item) {
              if (item is Map && item['msg'] is String) {
                return (item['msg'] as String).trim();
              }
              return item is String ? item.trim() : '';
            })
            .where((message) => message.isNotEmpty)
            .toList();
        if (messages.isNotEmpty) return messages.join(' ');
      }
    }

    final statusCode = result['statusCode'];
    if (statusCode is int && statusCode >= 500) {
      return 'The server could not complete the request. Please try again.';
    }
    return fallback;
  }

  static bool _isSuccessful(Map<String, dynamic> result) {
    final statusCode = result['statusCode'];
    return statusCode is int && statusCode >= 200 && statusCode < 300;
  }

  static VerificationApiException _verificationException(
    Map<String, dynamic> result, {
    required String fallback,
  }) {
    final detail = verificationDetailMap(result['body']);
    final code = detail?['code']?.toString().trim().toLowerCase() ?? '';
    final pending = PendingVerificationContext.tryParse(detail);
    final attemptsRemaining = _nonNegativeInt(detail?['attempts_remaining']);
    final retryAfterSeconds = _nonNegativeInt(detail?['retry_after_seconds']);
    final safeMessages = <String, String>{
      'verification_required':
          'Account verification is required before you can log in.',
      'invalid_otp': 'That verification code is incorrect. Please try again.',
      'expired_otp': 'That verification code has expired. Request a new code.',
      'otp_expired': 'That verification code has expired. Request a new code.',
      'attempts_exhausted':
          'Too many incorrect attempts. Request a new verification code.',
      'otp_attempts_exhausted':
          'Too many incorrect attempts. Request a new verification code.',
      'resend_cooldown': 'Please wait before requesting another code.',
      'otp_resend_cooldown': 'Please wait before requesting another code.',
      'resend_limit_exceeded':
          'The resend limit has been reached. Please try again later.',
      'otp_resend_limit':
          'The resend limit has been reached. Please try again later.',
      'provider_failure':
          'The verification code could not be delivered. Please try again.',
      'delivery_failed':
          'The verification code could not be delivered. Please try again.',
      'otp_delivery_unavailable':
          'The verification code could not be delivered. Please try again.',
      'otp_service_unavailable':
          'Verification is temporarily unavailable. Please try again.',
      'already_verified': 'This caregiver account is already verified.',
      'caregiver_already_verified':
          'This caregiver account is already verified.',
      'challenge_not_found':
          'No active verification request was found. Register again.',
      'verification_not_found':
          'No active verification request was found. Register again.',
      'otp_not_available':
          'No active verification code was found. Request a new code.',
      'channel_mismatch':
          'The verification channel does not match this request.',
      'verification_channel_mismatch':
          'The verification channel does not match this request.',
      'duplicate_verified':
          'An account already exists for this email address or phone number.',
      'caregiver_already_exists':
          'An account already exists for this email address or phone number.',
      'identity_conflict':
          'This email address or phone number belongs to another account.',
      'caregiver_registration_conflict':
          'This email address or phone number belongs to another account.',
      'verification_state_unavailable':
          'Account verification is temporarily unavailable. Please register again.',
      'verification_not_pending':
          'This caregiver account is not awaiting verification.',
      'otp_state_changed':
          'The verification request changed. Please request a new code.',
    };
    var message = safeMessages[code];
    message ??= errorMessage(result, fallback: fallback);
    if (attemptsRemaining != null &&
        attemptsRemaining > 0 &&
        (code == 'invalid_otp')) {
      message = '$message $attemptsRemaining attempt(s) remaining.';
    }

    return VerificationApiException(
      message,
      code: code.isEmpty ? 'request_failed' : code,
      pendingVerification: pending,
      attemptsRemaining: attemptsRemaining,
      retryAfterSeconds: retryAfterSeconds,
    );
  }

  static int? _nonNegativeInt(Object? value) {
    final parsed = value is int
        ? value
        : value is num
        ? value.toInt()
        : int.tryParse(value?.toString() ?? '');
    return parsed != null && parsed >= 0 ? parsed : null;
  }

  static Future<bool> checkBackendConnection() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/'));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['status'] == 'success';
      }

      return false;
    } catch (e) {
      return false;
    }
  }

  static Future<CaregiverRegistrationResult> registerCaregiver({
    required String name,
    required String phoneOrEmail,
    required String password,
    required CaregiverVerificationChannel channel,
  }) async {
    final result = await _postJson('/auth/register-caregiver', {
      'name': name,
      'phone_or_email': phoneOrEmail,
      'password': password,
      'channel': channel.apiValue,
    });

    if (!_isSuccessful(result)) {
      throw _verificationException(
        result,
        fallback: 'Registration failed. Please check your details.',
      );
    }

    final parsed = CaregiverRegistrationResult.tryParse(result['body']);
    if (parsed == null) {
      throw const ApiException(
        'The server returned an invalid registration response.',
      );
    }
    return parsed;
  }

  static Future<CaregiverLoginResult> loginCaregiver({
    required String phoneOrEmail,
    required String password,
  }) async {
    final result = await _postJson('/auth/login-caregiver', {
      'phone_or_email': phoneOrEmail,
      'password': password,
    });

    if (!_isSuccessful(result)) {
      throw _verificationException(
        result,
        fallback: 'Login failed. Please check your credentials.',
      );
    }

    final parsed = CaregiverLoginResult.tryParse(result['body']);
    if (parsed == null) {
      throw const ApiException(
        'The server returned an invalid authenticated session.',
      );
    }
    return parsed;
  }

  static Future<CaregiverVerificationResult> verifyCaregiverOtp({
    required int caregiverId,
    required CaregiverVerificationChannel channel,
    required String otp,
  }) async {
    final result = await _postJson('/auth/verify-otp', {
      'caregiver_id': caregiverId,
      'channel': channel.apiValue,
      'otp': otp,
    });

    if (!_isSuccessful(result)) {
      throw _verificationException(
        result,
        fallback: 'The verification code could not be verified.',
      );
    }

    final parsed = CaregiverVerificationResult.tryParse(result['body']);
    if (parsed == null || parsed.caregiverId != caregiverId) {
      throw const ApiException(
        'The server returned an invalid verification response.',
      );
    }
    return parsed;
  }

  static Future<CaregiverRegistrationResult> resendCaregiverOtp({
    required int caregiverId,
    required CaregiverVerificationChannel channel,
  }) async {
    final result = await _postJson('/auth/resend-otp', {
      'caregiver_id': caregiverId,
      'channel': channel.apiValue,
    });

    if (!_isSuccessful(result)) {
      throw _verificationException(
        result,
        fallback: 'A new verification code could not be sent.',
      );
    }

    final parsed = CaregiverRegistrationResult.tryParse(result['body']);
    if (parsed == null ||
        parsed.pendingVerification.caregiverId != caregiverId ||
        parsed.pendingVerification.channel != channel) {
      throw const ApiException(
        'The server returned an invalid resend response.',
      );
    }
    return parsed;
  }

  static Future<Map<String, dynamic>> createPatient({
    required int caregiverId,
    required String name,
    required int age,
    required String gender,
    required String phone,
    required String address,
    required String emergencyContact,
    required bool hasDiabetes,
    required bool hasHeartDisease,
    required bool hasHypertension,
    required bool hasKidneyDisease,
    required bool hasStrokeHistory,
    required String diseaseHistory,
  }) async {
    return _postJson('/patients/', {
      'caregiver_id': caregiverId,
      'name': name,
      'age': age,
      'gender': gender,
      'phone': phone,
      'address': address,
      'emergency_contact': emergencyContact,
      'has_diabetes': hasDiabetes,
      'has_heart_disease': hasHeartDisease,
      'has_hypertension': hasHypertension,
      'has_kidney_disease': hasKidneyDisease,
      'has_stroke_history': hasStrokeHistory,
      'disease_history': diseaseHistory,
    }, authenticated: true);
  }

  static Future<List<dynamic>> getPatients() async {
    final response = await http.get(
      Uri.parse('$baseUrl/patients/'),
      headers: await _headers(authenticated: true),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    return [];
  }

  static Future<List<dynamic>> getPatientsByCaregiver({
    required int caregiverId,
  }) async {
    final response = await http.get(
      Uri.parse('$baseUrl/patients/caregiver/$caregiverId'),
      headers: await _headers(authenticated: true),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    return [];
  }

  static Future<Map<String, dynamic>?> getPatientById({
    required int patientId,
  }) async {
    final response = await http.get(
      Uri.parse('$baseUrl/patients/$patientId'),
      headers: await _headers(authenticated: true),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);

      if (data is Map<String, dynamic>) {
        if (data.containsKey('message')) return null;
        return data;
      }
    }

    return null;
  }

  static Future<DailyObservation?> getTodayObservation({
    required int patientId,
  }) async {
    final response = await _getAuthenticated(
      '/patients/$patientId/observations/today',
    );
    if (response.statusCode == 404) return null;
    if (response.statusCode != 200) {
      _throwResponseError(
        response,
        fallback: 'Could not load today\'s health update.',
      );
    }
    final observation = DailyObservation.tryParse(
      decodeResponseObject(response.body),
    );
    if (observation == null || observation.patientId != patientId) {
      throw const ApiException(
        'The server returned an invalid daily observation.',
      );
    }
    return observation;
  }

  static Future<List<DailyObservation>> getPatientObservations({
    required int patientId,
  }) async {
    final response = await _getAuthenticated(
      '/patients/$patientId/observations',
    );
    if (response.statusCode != 200) {
      _throwResponseError(
        response,
        fallback: 'Could not load recent health observations.',
      );
    }

    final decoded = _decodeResponseList(response.body);
    final observations = <DailyObservation>[];
    for (final item in decoded) {
      final observation = DailyObservation.tryParse(item);
      if (observation == null || observation.patientId != patientId) {
        throw const ApiException(
          'The server returned an invalid daily observation list.',
        );
      }
      observations.add(observation);
    }
    return observations;
  }

  static Future<DailyObservation> createTodayObservation({
    required int patientId,
    required DailyObservationDraft observation,
  }) async {
    final result = await _postJson(
      '/patients/$patientId/observations/today',
      observation.toJson(),
      authenticated: true,
      requireAuthentication: true,
    );
    return _observationFromResult(
      result,
      patientId: patientId,
      fallback: 'Could not save today\'s health update.',
    );
  }

  static Future<DailyObservation> updateObservation({
    required int patientId,
    required int observationId,
    required DailyObservationDraft observation,
  }) async {
    final result = await _patchJson(
      '/patients/$patientId/observations/$observationId',
      observation.toJson(includeNulls: true),
      authenticated: true,
      requireAuthentication: true,
    );
    return _observationFromResult(
      result,
      patientId: patientId,
      fallback: 'Could not update today\'s health update.',
    );
  }

  static DailyObservation _observationFromResult(
    Map<String, dynamic> result, {
    required int patientId,
    required String fallback,
  }) {
    if (!_isSuccessful(result)) {
      throw ApiException(
        errorMessage(result, fallback: fallback),
        statusCode: result['statusCode'] as int?,
      );
    }
    final observation = DailyObservation.tryParse(result['body']);
    if (observation == null || observation.patientId != patientId) {
      throw const ApiException(
        'The server returned an invalid daily observation.',
      );
    }
    return observation;
  }

  static Future<Map<String, dynamic>> createAssessment({
    required int patientId,
    required int age,
    required int glucose,
    required int systolicBp,
    required int diastolicBp,
    required double bmi,
    required double heightCm,
    required double weightKg,
    required String note,
    required bool chestPain,
    required bool dizziness,
    required bool shortnessOfBreath,
    required bool excessiveThirst,
    required bool fatigue,
    required bool blurredVision,
    required String diabetesRisk,
    required String heartRisk,
    required String overallRisk,
    required String recommendation,
    DiabetesModelInput? diabetesModelInput,
    HeartModelInput? heartModelInput,
  }) async {
    return _postJson(
      '/assessments/',
      {
        'patient_id': patientId,
        'age': age,
        'glucose': glucose,
        'systolic_bp': systolicBp,
        'diastolic_bp': diastolicBp,
        'bmi': bmi,
        'height_cm': heightCm,
        'weight_kg': weightKg,
        'note': note,
        'chest_pain': chestPain,
        'dizziness': dizziness,
        'shortness_of_breath': shortnessOfBreath,
        'excessive_thirst': excessiveThirst,
        'fatigue': fatigue,
        'blurred_vision': blurredVision,
        'diabetes_risk': diabetesRisk,
        'heart_risk': heartRisk,
        'overall_risk': overallRisk,
        'recommendation': recommendation,
        if (diabetesModelInput != null)
          'diabetes_model_input': diabetesModelInput.toJson(),
        if (heartModelInput != null)
          'heart_model_input': heartModelInput.toJson(),
      },
      authenticated: true,
      requireAuthentication: true,
    );
  }

  static Future<PredictionContracts> getPredictionContracts() async {
    final response = await _getAuthenticated('/predictions/contracts');
    if (response.statusCode < 200 || response.statusCode >= 300) {
      _throwResponseError(
        response,
        fallback: 'Could not load the research-model input contract.',
      );
    }

    final contracts = PredictionContracts.tryParse(
      decodeResponseObject(response.body),
    );
    if (contracts == null) {
      throw const ApiException(
        'The server returned an invalid research-model contract.',
      );
    }
    return contracts;
  }

  static Future<DiseasePrediction> predictDiabetes({
    required int patientId,
    required DiabetesModelInput input,
  }) async {
    final result = await _postJson(
      '/predictions/diabetes',
      input.toJson(patientId: patientId),
      authenticated: true,
      requireAuthentication: true,
    );
    return _predictionFromResult(
      result,
      disease: 'diabetes',
      fallback: 'The diabetes research model could not complete screening.',
    );
  }

  static Future<DiseasePrediction> predictHeart({
    required int patientId,
    required HeartModelInput input,
  }) async {
    final result = await _postJson(
      '/predictions/heart',
      input.toJson(patientId: patientId),
      authenticated: true,
      requireAuthentication: true,
    );
    return _predictionFromResult(
      result,
      disease: 'heart',
      fallback: 'The heart research model could not complete screening.',
    );
  }

  static DiseasePrediction _predictionFromResult(
    Map<String, dynamic> result, {
    required String disease,
    required String fallback,
  }) {
    final statusCode = result['statusCode'];
    if (statusCode is! int || statusCode < 200 || statusCode >= 300) {
      throw ApiException(errorMessage(result, fallback: fallback));
    }

    final prediction = DiseasePrediction.tryParse(
      result['body'],
      diseaseHint: disease,
      standaloneResponse: true,
    );
    if (prediction == null ||
        prediction.disease != disease ||
        !prediction.isModelPrediction) {
      throw const ApiException(
        'The server returned an invalid research-model prediction.',
      );
    }
    return prediction;
  }

  static Future<List<dynamic>> getAssessments() async {
    final response = await http.get(
      Uri.parse('$baseUrl/assessments/'),
      headers: await _headers(authenticated: true),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    return [];
  }

  static Future<List<dynamic>> getPatientAssessments({
    required int patientId,
  }) async {
    final response = await http.get(
      Uri.parse('$baseUrl/assessments/patient/$patientId'),
      headers: await _headers(authenticated: true),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    return [];
  }

  static Future<Map<String, dynamic>> createPrescription({
    required int patientId,
    required String doctorName,
    required String note,
    Uint8List? imageBytes,
    String? imageName,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$baseUrl/prescriptions/'),
    );
    request.headers.addAll(
      await _headers(
        authenticated: true,
        includeJsonContentType: false,
        requireAuthentication: true,
      ),
    );

    request.fields['patient_id'] = patientId.toString();
    request.fields['doctor_name'] = doctorName;
    request.fields['note'] = note;

    if (imageBytes != null) {
      request.files.add(
        http.MultipartFile.fromBytes(
          'image',
          imageBytes,
          filename: imageName ?? 'prescription_image.jpg',
        ),
      );
    }

    final response = await _runRequest(() async {
      final streamedResponse = await request.send();
      return http.Response.fromStream(streamedResponse);
    });

    return {
      'statusCode': response.statusCode,
      'body': decodeResponseObject(response.body),
    };
  }

  static Future<List<dynamic>> getPatientPrescriptions({
    required int patientId,
  }) async {
    final response = await _getAuthenticated(
      '/prescriptions/patient/$patientId',
    );

    if (response.statusCode == 200) {
      return _decodeResponseList(response.body);
    }

    _throwResponseError(
      response,
      fallback: 'Could not load prescription history.',
    );
  }

  static Future<Map<String, dynamic>> createMedicine({
    required int patientId,
    int? prescriptionId,
    required String name,
    String? strength,
    String? dosage,
    String? frequency,
    String? duration,
    String? instructions,
    int? quantity,
    int? dailyDose,
    String? startDate,
    String? runOutDate,
    String? alertDate,
    String? note,
  }) async {
    return _postJson(
      '/medicines/',
      {
        'patient_id': patientId,
        'prescription_id': prescriptionId,
        'name': name,
        'strength': strength,
        'dosage': dosage,
        'frequency': frequency,
        'duration': duration,
        'instructions': instructions,
        'quantity': quantity,
        'daily_dose': dailyDose,
        'start_date': startDate,
        'run_out_date': runOutDate,
        'alert_date': alertDate,
        'note': note,
      },
      authenticated: true,
      requireAuthentication: true,
    );
  }

  static Future<List<dynamic>> getPatientMedicines({
    required int patientId,
  }) async {
    final response = await _getAuthenticated('/medicines/patient/$patientId');

    if (response.statusCode == 200) {
      return _decodeResponseList(response.body);
    }

    _throwResponseError(response, fallback: 'Could not load medicines.');
  }

  static Future<Map<String, dynamic>> confirmPrescription({
    required int prescriptionId,
    required List<Map<String, Object?>> medicines,
  }) {
    return _postJson(
      '/prescriptions/$prescriptionId/confirm',
      {'medicines': medicines},
      authenticated: true,
      requireAuthentication: true,
    );
  }

  static Future<PrescriptionExtractionResult> extractPrescription({
    required int prescriptionId,
  }) async {
    final headers = await _headers(
      authenticated: true,
      includeJsonContentType: false,
      requireAuthentication: true,
    );
    final response = await _runRequest(
      () => http.post(
        Uri.parse('$baseUrl/prescriptions/$prescriptionId/extract'),
        headers: headers,
      ),
      timeout: _ocrRequestTimeout,
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      _throwResponseError(
        response,
        fallback: 'Could not extract medicines from this prescription.',
      );
    }

    final result = PrescriptionExtractionResult.fromJson(
      decodeResponseObject(response.body),
    );
    if (result.prescriptionId != prescriptionId ||
        (result.status != PrescriptionOcrStatus.ready &&
            result.status != PrescriptionOcrStatus.failed)) {
      throw const ApiException(
        'The server returned an invalid prescription extraction response.',
      );
    }
    return result;
  }

  static Future<Uint8List> getPrescriptionImage({
    required int prescriptionId,
  }) async {
    final response = await _getAuthenticated(
      '/prescriptions/$prescriptionId/image',
    );

    if (response.statusCode != 200) {
      _throwResponseError(
        response,
        fallback: 'Could not load the prescription image.',
      );
    }

    final contentType = response.headers['content-type']
        ?.split(';')
        .first
        .trim()
        .toLowerCase();
    if (contentType != 'image/jpeg' && contentType != 'image/png') {
      throw const ApiException(
        'The server returned an invalid prescription image.',
      );
    }
    if (response.bodyBytes.isEmpty) {
      throw const ApiException('The prescription image is empty.');
    }

    return response.bodyBytes;
  }
}
