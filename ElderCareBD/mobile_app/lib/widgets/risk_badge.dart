import 'package:flutter/material.dart';

class RiskBadge extends StatelessWidget {
  final String riskLevel;

  const RiskBadge({super.key, required this.riskLevel});

  @override
  Widget build(BuildContext context) {
    return Chip(label: Text(riskLevel));
  }
}
