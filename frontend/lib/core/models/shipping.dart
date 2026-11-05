import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/money/money.dart';

double _reqDouble(Map<String, dynamic> json, String key) {
  final value = optDouble(json, key);
  if (value == null) throw FormatException('Field "$key": expected number, got null');
  return value;
}


/// Delivery types the server knows (`DeliveryOption.delivery_type`).
abstract final class DeliveryType {
  static const courier = 'courier';
  static const helmDash = 'helm_dash';
  static const clickAndCollect = 'click_and_collect';

  static String label(String? type) => switch (type) {
        courier => 'Courier',
        helmDash => 'Helm Dash (on-water delivery)',
        clickAndCollect => 'Click & collect',
        null => 'Not set',
        _ => type,
      };
}

/// An enabled Helm Dash operating area (`OperatingAreaSummary` / `AreaPublic`).
class OperatingAreaSummary {
  const OperatingAreaSummary({
    required this.id,
    required this.name,
    required this.centerLat,
    required this.centerLng,
    required this.radiusNm,
  });

  final String id;
  final String name;
  final double centerLat;
  final double centerLng;
  final double radiusNm;

  /// Radius in metres (1 nautical mile = 1852 m).
  double get radiusMetres => radiusNm * 1852;

  factory OperatingAreaSummary.fromJson(Map<String, dynamic> json) => OperatingAreaSummary(
        id: req<String>(json, 'id'),
        name: req<String>(json, 'name'),
        centerLat: _reqDouble(json, 'center_lat'),
        centerLng: _reqDouble(json, 'center_lng'),
        radiusNm: _reqDouble(json, 'radius_nm'),
      );
}

/// A product named by a restriction (`RestrictedProduct`).
class RestrictedProduct {
  const RestrictedProduct({required this.productId, required this.name, required this.sku});

  final String productId;
  final String name;
  final String sku;

  factory RestrictedProduct.fromJson(Map<String, dynamic> json) => RestrictedProduct(
        productId: req<String>(json, 'product_id'),
        name: req<String>(json, 'name'),
        sku: req<String>(json, 'sku'),
      );
}

/// One delivery option for the current cart (`DeliveryOption`).
class DeliveryOption {
  const DeliveryOption({
    required this.deliveryType,
    required this.available,
    required this.requiresQuote,
    this.reasonCode,
    this.reason,
    this.priceCents,
    this.serviceName,
    this.estimatedDays,
    this.pickupLocation,
    this.developmentRateCard = false,
    this.operatingAreas = const [],
  });

  final String deliveryType;
  final bool available;
  final String? reasonCode;

  /// Why the option is unavailable (server text, safe to show).
  final String? reason;
  final bool requiresQuote;

  /// Indicative price for the current cart; Helm Dash needs a quote (null).
  final int? priceCents;
  final String? serviceName;
  final int? estimatedDays;
  final String? pickupLocation;
  final bool developmentRateCard;
  final List<OperatingAreaSummary> operatingAreas;

  factory DeliveryOption.fromJson(Map<String, dynamic> json) => DeliveryOption(
        deliveryType: req<String>(json, 'delivery_type'),
        available: req<bool>(json, 'available'),
        reasonCode: opt<String>(json, 'reason_code'),
        reason: opt<String>(json, 'reason'),
        requiresQuote: req<bool>(json, 'requires_quote'),
        priceCents: optionalCentsFrom(json, 'price_cents'),
        serviceName: opt<String>(json, 'service_name'),
        estimatedDays: opt<int>(json, 'estimated_days'),
        pickupLocation: opt<String>(json, 'pickup_location'),
        developmentRateCard: opt<bool>(json, 'development_rate_card') ?? false,
        operatingAreas: [
          for (final a in mapList(json, 'operating_areas')) OperatingAreaSummary.fromJson(a),
        ],
      );
}

/// `GET /shipping/options`: what the current cart can use and why not.
class DeliveryOptions {
  const DeliveryOptions({
    required this.currency,
    required this.merchandiseSubtotalCents,
    required this.totalWeightGrams,
    required this.missingWeightProducts,
    required this.dangerousGoodsProducts,
    required this.freeShippingThresholdCents,
    required this.options,
  });

  final String currency;
  final int merchandiseSubtotalCents;
  final int? totalWeightGrams;
  final List<RestrictedProduct> missingWeightProducts;
  final List<RestrictedProduct> dangerousGoodsProducts;
  final int freeShippingThresholdCents;
  final List<DeliveryOption> options;

  DeliveryOption? option(String type) {
    for (final o in options) {
      if (o.deliveryType == type) return o;
    }
    return null;
  }

  factory DeliveryOptions.fromJson(Map<String, dynamic> json) => DeliveryOptions(
        currency: opt<String>(json, 'currency') ?? 'NZD',
        merchandiseSubtotalCents: centsFrom(json, 'merchandise_subtotal_cents'),
        totalWeightGrams: opt<int>(json, 'total_weight_grams'),
        missingWeightProducts: [
          for (final p in mapList(json, 'missing_weight_products')) RestrictedProduct.fromJson(p),
        ],
        dangerousGoodsProducts: [
          for (final p in mapList(json, 'dangerous_goods_products')) RestrictedProduct.fromJson(p),
        ],
        freeShippingThresholdCents: centsFrom(json, 'free_shipping_threshold_cents'),
        options: [for (final o in mapList(json, 'options')) DeliveryOption.fromJson(o)],
      );
}

/// A server-priced, single-use delivery quote bound to the user and cart
/// (`QuoteResponse`).
class DeliveryQuote {
  const DeliveryQuote({
    required this.id,
    required this.deliveryType,
    required this.provider,
    required this.serviceName,
    required this.priceCents,
    required this.currency,
    required this.destination,
    required this.parcelWeightGrams,
    required this.merchandiseSubtotalCents,
    required this.expiresAt,
    required this.createdAt,
    this.freeShippingThresholdCents,
    this.operatingAreaId,
    this.operatingAreaName,
    this.nauticalMiles,
    this.estimatedMinutes,
    this.estimatedDays,
    this.developmentRateCard = false,
  });

  final String id;
  final String deliveryType;
  final String provider;
  final String serviceName;
  final int priceCents;
  final String currency;
  final Map<String, dynamic> destination;
  final int parcelWeightGrams;
  final int merchandiseSubtotalCents;
  final int? freeShippingThresholdCents;
  final String? operatingAreaId;
  final String? operatingAreaName;
  final double? nauticalMiles;
  final int? estimatedMinutes;
  final int? estimatedDays;
  final bool developmentRateCard;
  final DateTime expiresAt;
  final DateTime createdAt;

  bool isExpired([DateTime? now]) => !(now ?? DateTime.now()).isBefore(expiresAt);

  String? get postcode => destination['postcode'] as String?;

  factory DeliveryQuote.fromJson(Map<String, dynamic> json) => DeliveryQuote(
        id: req<String>(json, 'id'),
        deliveryType: req<String>(json, 'delivery_type'),
        provider: req<String>(json, 'provider'),
        serviceName: req<String>(json, 'service_name'),
        priceCents: centsFrom(json, 'price_cents'),
        currency: opt<String>(json, 'currency') ?? 'NZD',
        destination: reqMap(json, 'destination'),
        parcelWeightGrams: req<int>(json, 'parcel_weight_grams'),
        merchandiseSubtotalCents: centsFrom(json, 'merchandise_subtotal_cents'),
        freeShippingThresholdCents: optionalCentsFrom(json, 'free_shipping_threshold_cents'),
        operatingAreaId: opt<String>(json, 'operating_area_id'),
        operatingAreaName: opt<String>(json, 'operating_area_name'),
        nauticalMiles: optDouble(json, 'nautical_miles'),
        estimatedMinutes: opt<int>(json, 'estimated_minutes'),
        estimatedDays: opt<int>(json, 'estimated_days'),
        developmentRateCard: opt<bool>(json, 'development_rate_card') ?? false,
        expiresAt: reqDate(json, 'expires_at'),
        createdAt: reqDate(json, 'created_at'),
      );
}

/// `POST /orders/checkout/preview`: exactly what checkout would charge now.
class CheckoutPreview {
  const CheckoutPreview({
    required this.currency,
    required this.deliveryType,
    required this.subtotalCents,
    required this.discountCents,
    required this.shippingCents,
    required this.totalCents,
    required this.freeShippingApplied,
    required this.freeShippingThresholdCents,
    required this.minChargeCents,
    this.quoteId,
    this.pickupLocation,
  });

  final String currency;
  final String deliveryType;
  final String? quoteId;
  final int subtotalCents;
  final int discountCents;
  final int shippingCents;
  final int totalCents;
  final bool freeShippingApplied;
  final int freeShippingThresholdCents;
  final int minChargeCents;
  final String? pickupLocation;

  factory CheckoutPreview.fromJson(Map<String, dynamic> json) => CheckoutPreview(
        currency: opt<String>(json, 'currency') ?? 'NZD',
        deliveryType: req<String>(json, 'delivery_type'),
        quoteId: opt<String>(json, 'quote_id'),
        subtotalCents: centsFrom(json, 'subtotal_cents'),
        discountCents: centsFrom(json, 'discount_cents'),
        shippingCents: centsFrom(json, 'shipping_cents'),
        totalCents: centsFrom(json, 'total_cents'),
        freeShippingApplied: req<bool>(json, 'free_shipping_applied'),
        freeShippingThresholdCents: centsFrom(json, 'free_shipping_threshold_cents'),
        minChargeCents: centsFrom(json, 'min_charge_cents'),
        pickupLocation: opt<String>(json, 'pickup_location'),
      );
}

/// NZ courier address (`ShippingAddress`).
class ShippingAddress {
  const ShippingAddress({
    required this.name,
    required this.line1,
    required this.city,
    required this.postcode,
    required this.phone,
    this.line2,
    this.suburb,
  });

  final String name;
  final String line1;
  final String? line2;
  final String? suburb;
  final String city;
  final String postcode;
  final String phone;

  static final postcodePattern = RegExp(r'^\d{4}$');
  static final phonePattern = RegExp(r'^\+?[0-9 ()\-]{6,20}$');

  Map<String, dynamic> toJson() => {
        'name': name,
        'line1': line1,
        if (line2 != null && line2!.isNotEmpty) 'line2': line2,
        if (suburb != null && suburb!.isNotEmpty) 'suburb': suburb,
        'city': city,
        'postcode': postcode,
        'phone': phone,
      };
}

/// Vessel contact for Helm Dash (`HelmDashContact`).
class HelmDashContact {
  const HelmDashContact({required this.vesselName, required this.phone, this.note});

  final String vesselName;
  final String phone;
  final String? note;

  Map<String, dynamic> toJson() => {
        'vessel_name': vesselName,
        'phone': phone,
        if (note != null && note!.isNotEmpty) 'note': note,
      };
}

/// Body of `POST /orders/checkout` and `/orders/checkout/preview`.
class CheckoutRequest {
  const CheckoutRequest({
    required this.deliveryType,
    this.quoteId,
    this.shippingAddress,
    this.helmDashContact,
    this.discountEntitlementId,
    this.notes,
  });

  final String deliveryType;
  final String? quoteId;
  final ShippingAddress? shippingAddress;
  final HelmDashContact? helmDashContact;
  final String? discountEntitlementId;
  final String? notes;

  Map<String, dynamic> toJson() => {
        'delivery_type': deliveryType,
        'quote_id': ?quoteId,
        if (shippingAddress != null) 'shipping_address': shippingAddress!.toJson(),
        if (helmDashContact != null) 'helm_dash_contact': helmDashContact!.toJson(),
        'discount_entitlement_id': ?discountEntitlementId,
        if (notes != null && notes!.trim().isNotEmpty) 'notes': notes!.trim(),
        'payment_method': 'card',
      };
}
