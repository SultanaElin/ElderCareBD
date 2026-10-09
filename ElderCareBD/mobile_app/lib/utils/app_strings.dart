import 'package:flutter/widgets.dart';

class AppStrings {
  const AppStrings._(this._values);

  final Map<String, String> _values;

  static const english = AppStrings._({
    'login': 'Login',
    'register': 'Register',
    'verifyOtp': 'Verify OTP',
    'caregiverLogin': 'Caregiver Login',
    'caregiverRegister': 'Caregiver Register',
    'verifyCaregiverAccount': 'Verify Caregiver Account',
    'verifyCode': 'Verify Code',
    'dashboard': 'Dashboard',
    'patients': 'Patients',
    'addPatient': 'Add Patient',
    'assessment': 'Assessment',
    'diabetesScreening': 'DiaBD diabetes status screening',
    'heartScreening': 'Heart screening',
    'prescription': 'Prescription',
    'history': 'History',
    'save': 'Save',
    'confirm': 'Confirm',
    'cancel': 'Cancel',
    'retry': 'Retry',
    'resendOtp': 'Resend OTP',
    'noData': 'No data',
    'error': 'Error',
    'loading': 'Loading',
    'language': 'বাংলা',
  });

  static const bangla = AppStrings._({
    'login': 'লগইন',
    'register': 'নিবন্ধন',
    'verifyOtp': 'ওটিপি যাচাই',
    'caregiverLogin': 'কেয়ারগিভার লগইন',
    'caregiverRegister': 'কেয়ারগিভার নিবন্ধন',
    'verifyCaregiverAccount': 'কেয়ারগিভার অ্যাকাউন্ট যাচাই',
    'verifyCode': 'কোড যাচাই',
    'dashboard': 'ড্যাশবোর্ড',
    'patients': 'রোগী',
    'addPatient': 'রোগী যোগ করুন',
    'assessment': 'স্বাস্থ্য মূল্যায়ন',
    'diabetesScreening': 'ডায়াবেটিস স্ক্রিনিং',
    'heartScreening': 'হৃদ্‌রোগ স্ক্রিনিং',
    'prescription': 'প্রেসক্রিপশন',
    'history': 'ইতিহাস',
    'save': 'সংরক্ষণ',
    'confirm': 'নিশ্চিত করুন',
    'cancel': 'বাতিল',
    'retry': 'আবার চেষ্টা করুন',
    'resendOtp': 'ওটিপি আবার পাঠান',
    'noData': 'কোনো তথ্য নেই',
    'error': 'ত্রুটি',
    'loading': 'লোড হচ্ছে',
    'language': 'English',
  });

  static AppStrings of(BuildContext context) {
    return Localizations.localeOf(context).languageCode == 'bn'
        ? bangla
        : english;
  }

  String get login => _values['login']!;
  String get register => _values['register']!;
  String get verifyOtp => _values['verifyOtp']!;
  String get caregiverLogin => _values['caregiverLogin']!;
  String get caregiverRegister => _values['caregiverRegister']!;
  String get verifyCaregiverAccount => _values['verifyCaregiverAccount']!;
  String get verifyCode => _values['verifyCode']!;
  String get dashboard => _values['dashboard']!;
  String get patients => _values['patients']!;
  String get addPatient => _values['addPatient']!;
  String get assessment => _values['assessment']!;
  String get diabetesScreening => _values['diabetesScreening']!;
  String get heartScreening => _values['heartScreening']!;
  String get prescription => _values['prescription']!;
  String get history => _values['history']!;
  String get save => _values['save']!;
  String get confirm => _values['confirm']!;
  String get cancel => _values['cancel']!;
  String get retry => _values['retry']!;
  String get resendOtp => _values['resendOtp']!;
  String get noData => _values['noData']!;
  String get error => _values['error']!;
  String get loading => _values['loading']!;
  String get language => _values['language']!;
}
