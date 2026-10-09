enum CaregiverVerificationChannel {
  email('email', 'Email'),
  sms('sms', 'SMS');

  const CaregiverVerificationChannel(this.apiValue, this.displayLabel);

  final String apiValue;
  final String displayLabel;

  static CaregiverVerificationChannel? tryParse(Object? value) {
    final normalized = value?.toString().trim().toLowerCase();
    for (final channel in values) {
      if (channel.apiValue == normalized) return channel;
    }
    return null;
  }
}

class PendingVerificationContext {
  const PendingVerificationContext({
    required this.caregiverId,
    required this.channel,
    required this.destinationHint,
    required this.expiresAt,
    required this.resendAvailableAt,
  });

  final int caregiverId;
  final CaregiverVerificationChannel channel;
  final String destinationHint;
  final DateTime expiresAt;
  final DateTime resendAvailableAt;

  PendingVerificationContext copyWith({
    DateTime? expiresAt,
    DateTime? resendAvailableAt,
  }) {
    return PendingVerificationContext(
      caregiverId: caregiverId,
      channel: channel,
      destinationHint: destinationHint,
      expiresAt: expiresAt ?? this.expiresAt,
      resendAvailableAt: resendAvailableAt ?? this.resendAvailableAt,
    );
  }

  Map<String, Object> toJson() {
    return {
      'caregiver_id': caregiverId,
      'channel': channel.apiValue,
      'destination_hint': destinationHint,
      'expires_at': expiresAt.toUtc().toIso8601String(),
      'resend_available_at': resendAvailableAt.toUtc().toIso8601String(),
    };
  }

  static PendingVerificationContext? tryParse(Object? value) {
    final body = _stringKeyedMap(value);
    if (body == null) return null;

    final caregiverId = _positiveInt(body['caregiver_id']);
    final channel = CaregiverVerificationChannel.tryParse(body['channel']);
    final destinationHint = body['destination_hint']?.toString().trim() ?? '';
    final expiresAt = _utcDateTime(body['expires_at']);
    final resendAvailableAt = _utcDateTime(body['resend_available_at']);

    if (caregiverId == null ||
        channel == null ||
        destinationHint.isEmpty ||
        expiresAt == null ||
        resendAvailableAt == null) {
      return null;
    }

    return PendingVerificationContext(
      caregiverId: caregiverId,
      channel: channel,
      destinationHint: destinationHint,
      expiresAt: expiresAt,
      resendAvailableAt: resendAvailableAt,
    );
  }
}

class CaregiverRegistrationResult {
  const CaregiverRegistrationResult({
    required this.message,
    required this.pendingVerification,
  });

  final String message;
  final PendingVerificationContext pendingVerification;

  static CaregiverRegistrationResult? tryParse(Object? value) {
    final body = _stringKeyedMap(value);
    final pending = PendingVerificationContext.tryParse(value);
    if (body == null ||
        pending == null ||
        body['verification_required'] != true ||
        body.containsKey('access_token')) {
      return null;
    }

    return CaregiverRegistrationResult(
      message: _message(body['message'], 'Verification is required.'),
      pendingVerification: pending,
    );
  }
}

class CaregiverVerificationResult {
  const CaregiverVerificationResult({
    required this.message,
    required this.caregiverId,
  });

  final String message;
  final int caregiverId;

  static CaregiverVerificationResult? tryParse(Object? value) {
    final body = _stringKeyedMap(value);
    if (body == null ||
        body['verified'] != true ||
        body['verification_required'] != false ||
        body.containsKey('access_token')) {
      return null;
    }

    final caregiverId = _positiveInt(body['caregiver_id']);
    if (caregiverId == null) return null;

    return CaregiverVerificationResult(
      message: _message(body['message'], 'Caregiver verified successfully.'),
      caregiverId: caregiverId,
    );
  }
}

class CaregiverLoginResult {
  const CaregiverLoginResult({
    required this.caregiverId,
    required this.caregiverName,
    required this.accessToken,
  });

  final int caregiverId;
  final String caregiverName;
  final String accessToken;

  static CaregiverLoginResult? tryParse(Object? value) {
    final body = _stringKeyedMap(value);
    if (body == null) return null;

    final caregiverId = _positiveInt(body['caregiver_id']);
    final caregiverName = body['name']?.toString().trim() ?? '';
    final accessToken = body['access_token']?.toString().trim() ?? '';
    if (caregiverId == null || accessToken.isEmpty) return null;

    return CaregiverLoginResult(
      caregiverId: caregiverId,
      caregiverName: caregiverName.isEmpty ? 'Caregiver' : caregiverName,
      accessToken: accessToken,
    );
  }
}

Map<String, dynamic>? verificationDetailMap(Object? responseBody) {
  final body = _stringKeyedMap(responseBody);
  if (body == null) return null;
  return _stringKeyedMap(body['detail']);
}

Map<String, dynamic>? _stringKeyedMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) {
    return value.map((key, item) => MapEntry(key.toString(), item));
  }
  return null;
}

int? _positiveInt(Object? value) {
  final parsed = value is int
      ? value
      : value is num
      ? value.toInt()
      : int.tryParse(value?.toString() ?? '');
  return parsed != null && parsed > 0 ? parsed : null;
}

DateTime? _utcDateTime(Object? value) {
  final parsed = DateTime.tryParse(value?.toString() ?? '');
  if (parsed == null || !parsed.isUtc) return null;
  return parsed.toUtc();
}

String _message(Object? value, String fallback) {
  final message = value?.toString().trim() ?? '';
  return message.isEmpty ? fallback : message;
}
