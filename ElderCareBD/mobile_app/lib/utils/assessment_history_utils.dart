import 'package:intl/intl.dart';

DateTime? parseAssessmentTimestampToLocal(dynamic rawTimestamp) {
  if (rawTimestamp == null || rawTimestamp.toString().isEmpty) {
    return null;
  }

  final parsed = rawTimestamp is DateTime
      ? rawTimestamp
      : DateTime.tryParse(rawTimestamp.toString());

  if (parsed == null) {
    return null;
  }

  final utcTimestamp = parsed.isUtc
      ? parsed
      : DateTime.utc(
          parsed.year,
          parsed.month,
          parsed.day,
          parsed.hour,
          parsed.minute,
          parsed.second,
          parsed.millisecond,
          parsed.microsecond,
        );

  return utcTimestamp.toLocal();
}

String formatAssessmentTimestamp(dynamic rawTimestamp) {
  final localTimestamp = parseAssessmentTimestampToLocal(rawTimestamp);

  if (localTimestamp == null) {
    if (rawTimestamp == null || rawTimestamp.toString().isEmpty) {
      return 'Not available';
    }
    return rawTimestamp.toString();
  }

  return DateFormat('dd MMM yyyy, hh:mm a').format(localTimestamp);
}

List<String> activeAssessmentSymptomLabels(Map<String, dynamic> assessment) {
  const symptomLabels = <String, String>{
    'chest_pain': 'Chest pain',
    'dizziness': 'Dizziness',
    'shortness_of_breath': 'Shortness of breath',
    'excessive_thirst': 'Excessive thirst',
    'fatigue': 'Fatigue',
    'blurred_vision': 'Blurred vision',
  };

  return symptomLabels.entries
      .where((entry) => assessment[entry.key] == true)
      .map((entry) => entry.value)
      .toList();
}
