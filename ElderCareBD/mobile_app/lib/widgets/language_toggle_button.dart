import 'package:flutter/material.dart';

import '../services/app_language_service.dart';
import '../utils/app_strings.dart';

class LanguageToggleButton extends StatelessWidget {
  const LanguageToggleButton({super.key});

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: AppLanguageService.toggle,
      icon: const Icon(Icons.translate_rounded),
      label: Text(AppStrings.of(context).language),
    );
  }
}
