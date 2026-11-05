import 'package:helm_marine/core/models/json.dart';

/// A payment method and, when disabled, the server's recorded reason.
class PaymentMethodConfig {
  const PaymentMethodConfig({required this.id, required this.enabled, this.reason});

  final String id;
  final bool enabled;
  final String? reason;

  factory PaymentMethodConfig.fromJson(Map<String, dynamic> json) => PaymentMethodConfig(
        id: req<String>(json, 'id'),
        enabled: req<bool>(json, 'enabled'),
        reason: opt<String>(json, 'reason'),
      );
}

class PaymentsConfig {
  const PaymentsConfig({
    required this.provider,
    required this.localTestMode,
    required this.methods,
    this.stripePublishableKey,
  });

  /// `stripe`, `local` (development substitute) or `disabled`.
  final String provider;
  final String? stripePublishableKey;
  final bool localTestMode;
  final List<PaymentMethodConfig> methods;

  bool get enabled => provider != 'disabled';

  PaymentMethodConfig? method(String id) {
    for (final m in methods) {
      if (m.id == id) return m;
    }
    return null;
  }

  factory PaymentsConfig.fromJson(Map<String, dynamic> json) => PaymentsConfig(
        provider: req<String>(json, 'provider'),
        stripePublishableKey: opt<String>(json, 'stripe_publishable_key'),
        localTestMode: req<bool>(json, 'local_test_mode'),
        methods: [
          for (final m in mapList(json, 'methods')) PaymentMethodConfig.fromJson(m),
        ],
      );
}

/// Whether a delivery option is offered, and why not when it isn't.
class DeliveryOptionConfig {
  const DeliveryOptionConfig({required this.enabled, this.reason, this.extra = const {}});

  final bool enabled;
  final String? reason;

  /// Option-specific fields (`service_name`, `location`, `development_rate_card`).
  final Map<String, dynamic> extra;

  factory DeliveryOptionConfig.fromJson(Map<String, dynamic> json) => DeliveryOptionConfig(
        enabled: req<bool>(json, 'enabled'),
        reason: opt<String>(json, 'reason'),
        extra: {
          for (final e in json.entries)
            if (e.key != 'enabled' && e.key != 'reason') e.key: e.value,
        },
      );
}

class DeliveryConfig {
  const DeliveryConfig({
    required this.courier,
    required this.helmDash,
    required this.clickAndCollect,
    required this.freeShippingThresholdCents,
    required this.dangerousGoodsDeliveryTypes,
  });

  final DeliveryOptionConfig courier;
  final DeliveryOptionConfig helmDash;
  final DeliveryOptionConfig clickAndCollect;
  final int? freeShippingThresholdCents;
  final List<String> dangerousGoodsDeliveryTypes;

  String? get clickAndCollectLocation => clickAndCollect.extra['location'] as String?;

  factory DeliveryConfig.fromJson(Map<String, dynamic> json) => DeliveryConfig(
        courier: DeliveryOptionConfig.fromJson(reqMap(json, 'courier')),
        helmDash: DeliveryOptionConfig.fromJson(reqMap(json, 'helm_dash')),
        clickAndCollect: DeliveryOptionConfig.fromJson(reqMap(json, 'click_and_collect')),
        freeShippingThresholdCents: opt<int>(json, 'free_shipping_threshold_cents'),
        dangerousGoodsDeliveryTypes: stringList(json, 'dangerous_goods_delivery_types'),
      );
}

class AiConfig {
  const AiConfig({required this.enabled, required this.mode, required this.localSubstitute});

  final bool enabled;
  final String mode;

  /// True when answers come from the deterministic local substitute (dev only).
  final bool localSubstitute;

  factory AiConfig.fromJson(Map<String, dynamic> json) => AiConfig(
        enabled: req<bool>(json, 'enabled'),
        mode: req<String>(json, 'mode'),
        localSubstitute: req<bool>(json, 'local_substitute'),
      );
}

class ContentConfig {
  const ContentConfig({required this.provider, required this.localFixture});

  final String provider;
  final bool localFixture;

  factory ContentConfig.fromJson(Map<String, dynamic> json) => ContentConfig(
        provider: req<String>(json, 'provider'),
        localFixture: req<bool>(json, 'local_fixture'),
      );
}

/// Non-secret server configuration from `GET /api/v1/config/public`, used to
/// decide which features to show and why something is unavailable.
class PublicConfig {
  const PublicConfig({
    required this.environment,
    required this.currency,
    required this.payments,
    required this.delivery,
    required this.ai,
    required this.content,
    this.searchBackend,
    this.mapboxPublicToken,
    this.warehouseLat,
    this.warehouseLng,
  });

  final String environment;
  final String currency;
  final PaymentsConfig payments;
  final DeliveryConfig delivery;
  final AiConfig ai;
  final ContentConfig content;
  final String? searchBackend;
  final String? mapboxPublicToken;
  final double? warehouseLat;
  final double? warehouseLng;

  factory PublicConfig.fromJson(Map<String, dynamic> json) {
    final warehouse = optMap(json, 'warehouse');
    return PublicConfig(
      environment: req<String>(json, 'environment'),
      currency: req<String>(json, 'currency'),
      payments: PaymentsConfig.fromJson(reqMap(json, 'payments')),
      delivery: DeliveryConfig.fromJson(reqMap(json, 'delivery')),
      ai: AiConfig.fromJson(reqMap(json, 'ai')),
      content: ContentConfig.fromJson(reqMap(json, 'content')),
      searchBackend: optMap(json, 'search')?['backend'] as String?,
      mapboxPublicToken: opt<String>(json, 'mapbox_public_token'),
      warehouseLat: warehouse == null ? null : optDouble(warehouse, 'lat'),
      warehouseLng: warehouse == null ? null : optDouble(warehouse, 'lng'),
    );
  }
}
