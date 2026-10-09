import 'package:flutter/material.dart';

import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';

class AppCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;

  const AppCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(AppSpacing.md),
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final borderRadius = BorderRadius.circular(AppSpacing.cardRadius);
    final cardContent = onTap == null
        ? Padding(padding: padding, child: child)
        : InkWell(
            borderRadius: borderRadius,
            onTap: onTap,
            child: Padding(padding: padding, child: child),
          );

    return DecoratedBox(
      decoration: BoxDecoration(borderRadius: borderRadius),
      child: Material(
        color: AppColors.card,
        shape: RoundedRectangleBorder(
          borderRadius: borderRadius,
          side: const BorderSide(color: AppColors.border),
        ),
        clipBehavior: Clip.antiAlias,
        child: cardContent,
      ),
    );
  }
}
