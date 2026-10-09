import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

class AppLanguageService {
  AppLanguageService._();

  static const _languageKey = 'app_language_code';
  static final locale = ValueNotifier<Locale>(const Locale('en'));

  static Future<void> restore() async {
    final preferences = await SharedPreferences.getInstance();
    locale.value = Locale(
      preferences.getString(_languageKey) == 'bn' ? 'bn' : 'en',
    );
  }

  static Future<void> toggle() async {
    final next = locale.value.languageCode == 'bn' ? 'en' : 'bn';
    locale.value = Locale(next);
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_languageKey, next);
  }
}
