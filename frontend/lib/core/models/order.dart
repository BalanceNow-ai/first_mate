import 'package:helm_marine/core/models/json.dart';
import 'package:helm_marine/core/money/money.dart';

DateTime? _optDate(Map<String, dynamic> json, String key) {
  final v = opt<String>(json, key);
  return v == null ? null : DateTime.parse(v);
}

/// Human labels for order statuses (`ORDER_STATUSES`).
String orderStatusLabel(String status) => switch (status) {
      'pending_payment' => 'Awaiting payment',
      'paid' => 'Paid',
      'ready_for_dispatch' => 'Packed — ready for dispatch',
      'dispatched' => 'Dispatched',
      'delivered' => 'Delivered',
      'collected' => 'Collected',
      'cancelled' => 'Cancelled',
      'expired' => 'Expired — reservation timed out',
      'refunded' => 'Refunded',
      'payment_review' => 'Payment under review',
      _ => status,
    };

/// Human labels for payment statuses (`PAYMENT_STATUSES`).
String paymentStatusLabel(String status) => switch (status) {
      'unpaid' => 'Not paid',
      'requires_action' => 'Authentication required',
      'processing' => 'Processing',
      'failed' => 'Payment failed',
      'succeeded' => 'Paid',
      'partially_refunded' => 'Partially refunded',
      'refunded' => 'Refunded',
      _ => status,
    };

/// One line of an order (`OrderItemResponse`).
class OrderItem {
  const OrderItem({
    required this.id,
    required this.productId,
    required this.productName,
    required this.sku,
    required this.quantity,
    required this.listPriceCents,
    required this.unitPriceCents,
    required this.lineTotalCents,
  });

  final String id;
  final String productId;
  final String productName;
  final String sku;
  final int quantity;
  final int listPriceCents;
  final int unitPriceCents;
  final int lineTotalCents;

  factory OrderItem.fromJson(Map<String, dynamic> json) => OrderItem(
        id: req<String>(json, 'id'),
        productId: req<String>(json, 'product_id'),
        productName: req<String>(json, 'product_name'),
        sku: req<String>(json, 'sku'),
        quantity: req<int>(json, 'quantity'),
        listPriceCents: centsFrom(json, 'list_price_cents'),
        unitPriceCents: centsFrom(json, 'unit_price_cents'),
        lineTotalCents: centsFrom(json, 'line_total_cents'),
      );
}

/// How the order is delivered (`DeliveryInfo`).
class OrderDelivery {
  const OrderDelivery({
    required this.deliveryType,
    this.shippingAddress,
    this.helmDash,
    this.pickupLocation,
    this.quoteId,
    this.serviceName,
    this.estimatedDays,
    this.estimatedMinutes,
    this.freeShippingApplied = false,
  });

  final String? deliveryType;
  final Map<String, dynamic>? shippingAddress;

  /// Helm Dash destination and vessel contact (`lat`, `lng`, `location_name`,
  /// `vessel_name`, `phone`, `note`, ...).
  final Map<String, dynamic>? helmDash;
  final String? pickupLocation;
  final String? quoteId;
  final String? serviceName;
  final int? estimatedDays;
  final int? estimatedMinutes;
  final bool freeShippingApplied;

  factory OrderDelivery.fromJson(Map<String, dynamic> json) => OrderDelivery(
        deliveryType: opt<String>(json, 'delivery_type'),
        shippingAddress: optMap(json, 'shipping_address'),
        helmDash: optMap(json, 'helm_dash'),
        pickupLocation: opt<String>(json, 'pickup_location'),
        quoteId: opt<String>(json, 'quote_id'),
        serviceName: opt<String>(json, 'service_name'),
        estimatedDays: opt<int>(json, 'estimated_days'),
        estimatedMinutes: opt<int>(json, 'estimated_minutes'),
        freeShippingApplied: opt<bool>(json, 'free_shipping_applied') ?? false,
      );
}

/// Courier tracking (`TrackingInfo`). `isTest` marks local test bookings.
class OrderTracking {
  const OrderTracking({this.trackingNumber, this.courier, this.shipmentStatus, this.isTest = false});

  final String? trackingNumber;
  final String? courier;
  final String? shipmentStatus;
  final bool isTest;

  bool get hasAny => trackingNumber != null || courier != null || shipmentStatus != null;

  factory OrderTracking.fromJson(Map<String, dynamic> json) => OrderTracking(
        trackingNumber: opt<String>(json, 'tracking_number'),
        courier: opt<String>(json, 'courier'),
        shipmentStatus: opt<String>(json, 'shipment_status'),
        isTest: opt<bool>(json, 'is_test') ?? false,
      );
}

/// An order (`OrderResponse`, or `StaffOrderResponse` when [userId] is set).
class Order {
  const Order({
    required this.id,
    required this.orderNumber,
    required this.status,
    required this.paymentStatus,
    required this.currency,
    required this.subtotalCents,
    required this.discountCents,
    required this.shippingCents,
    required this.totalCents,
    required this.refundedCents,
    required this.delivery,
    required this.items,
    required this.canCancel,
    required this.canRetryPayment,
    required this.tracking,
    required this.createdAt,
    required this.updatedAt,
    this.discountEntitlementId,
    this.paymentProvider,
    this.paymentIntentId,
    this.expiresAt,
    this.paidAt,
    this.cancelledAt,
    this.cancelReason,
    this.notes,
    this.userId,
    this.reviewReason,
  });

  final String id;
  final String orderNumber;
  final String status;
  final String paymentStatus;
  final String currency;
  final int subtotalCents;
  final int discountCents;
  final int shippingCents;
  final int totalCents;
  final int refundedCents;
  final String? discountEntitlementId;
  final String? paymentProvider;
  final String? paymentIntentId;
  final OrderDelivery delivery;
  final List<OrderItem> items;
  final DateTime? expiresAt;
  final DateTime? paidAt;
  final DateTime? cancelledAt;
  final String? cancelReason;
  final String? notes;
  final bool canCancel;
  final bool canRetryPayment;
  final OrderTracking tracking;
  final DateTime createdAt;
  final DateTime updatedAt;

  /// Staff view only.
  final String? userId;
  final String? reviewReason;

  bool get isPendingPayment => status == 'pending_payment';
  bool get isPaid => paidAt != null || const {'succeeded', 'partially_refunded', 'refunded'}.contains(paymentStatus);
  bool get isHelmDash => delivery.deliveryType == 'helm_dash';

  factory Order.fromJson(Map<String, dynamic> json) => Order(
        id: req<String>(json, 'id'),
        orderNumber: req<String>(json, 'order_number'),
        status: req<String>(json, 'status'),
        paymentStatus: req<String>(json, 'payment_status'),
        currency: req<String>(json, 'currency'),
        subtotalCents: centsFrom(json, 'subtotal_cents'),
        discountCents: centsFrom(json, 'discount_cents'),
        shippingCents: centsFrom(json, 'shipping_cents'),
        totalCents: centsFrom(json, 'total_cents'),
        refundedCents: centsFrom(json, 'refunded_cents'),
        discountEntitlementId: opt<String>(json, 'discount_entitlement_id'),
        paymentProvider: opt<String>(json, 'payment_provider'),
        paymentIntentId: opt<String>(json, 'payment_intent_id'),
        delivery: OrderDelivery.fromJson(reqMap(json, 'delivery')),
        items: [for (final i in mapList(json, 'items')) OrderItem.fromJson(i)],
        expiresAt: _optDate(json, 'expires_at'),
        paidAt: _optDate(json, 'paid_at'),
        cancelledAt: _optDate(json, 'cancelled_at'),
        cancelReason: opt<String>(json, 'cancel_reason'),
        notes: opt<String>(json, 'notes'),
        canCancel: req<bool>(json, 'can_cancel'),
        canRetryPayment: req<bool>(json, 'can_retry_payment'),
        tracking: OrderTracking.fromJson(reqMap(json, 'tracking')),
        createdAt: reqDate(json, 'created_at'),
        updatedAt: reqDate(json, 'updated_at'),
        userId: opt<String>(json, 'user_id'),
        reviewReason: opt<String>(json, 'review_reason'),
      );
}

/// A row of the order history (`OrderSummary` / `StaffOrderSummary`).
class OrderSummary {
  const OrderSummary({
    required this.id,
    required this.orderNumber,
    required this.status,
    required this.paymentStatus,
    required this.currency,
    required this.totalCents,
    required this.refundedCents,
    required this.itemCount,
    required this.createdAt,
    this.deliveryType,
    this.expiresAt,
    this.userId,
    this.reviewReason,
  });

  final String id;
  final String orderNumber;
  final String status;
  final String paymentStatus;
  final String currency;
  final int totalCents;
  final int refundedCents;
  final String? deliveryType;
  final int itemCount;
  final DateTime? expiresAt;
  final DateTime createdAt;
  final String? userId;
  final String? reviewReason;

  factory OrderSummary.fromJson(Map<String, dynamic> json) => OrderSummary(
        id: req<String>(json, 'id'),
        orderNumber: req<String>(json, 'order_number'),
        status: req<String>(json, 'status'),
        paymentStatus: req<String>(json, 'payment_status'),
        currency: req<String>(json, 'currency'),
        totalCents: centsFrom(json, 'total_cents'),
        refundedCents: centsFrom(json, 'refunded_cents'),
        deliveryType: opt<String>(json, 'delivery_type'),
        itemCount: req<int>(json, 'item_count'),
        expiresAt: _optDate(json, 'expires_at'),
        createdAt: reqDate(json, 'created_at'),
        userId: opt<String>(json, 'user_id'),
        reviewReason: opt<String>(json, 'review_reason'),
      );
}

/// A page of orders (`OrderListResponse` / `StaffOrderListResponse`).
class OrderPage {
  const OrderPage({required this.items, required this.total, required this.page, required this.pageSize});

  final List<OrderSummary> items;
  final int total;
  final int page;
  final int pageSize;

  int get pageCount => total == 0 ? 1 : ((total + pageSize - 1) ~/ pageSize);
  bool get hasNext => page < pageCount;

  factory OrderPage.fromJson(Map<String, dynamic> json) => OrderPage(
        items: [for (final i in mapList(json, 'items')) OrderSummary.fromJson(i)],
        total: req<int>(json, 'total'),
        page: req<int>(json, 'page'),
        pageSize: req<int>(json, 'page_size'),
      );
}

/// `POST /orders/{id}/refund` (202).
class RefundResult {
  const RefundResult({
    required this.orderId,
    required this.provider,
    required this.refundId,
    required this.status,
    required this.amountCents,
    required this.testMode,
    required this.refundedCents,
    required this.paymentStatus,
    required this.orderStatus,
    this.eventOutcome,
  });

  final String orderId;
  final String provider;
  final String refundId;
  final String status;
  final int amountCents;
  final bool testMode;
  final String? eventOutcome;
  final int refundedCents;
  final String paymentStatus;
  final String orderStatus;

  factory RefundResult.fromJson(Map<String, dynamic> json) => RefundResult(
        orderId: req<String>(json, 'order_id'),
        provider: req<String>(json, 'provider'),
        refundId: req<String>(json, 'refund_id'),
        status: req<String>(json, 'status'),
        amountCents: centsFrom(json, 'amount_cents'),
        testMode: req<bool>(json, 'test_mode'),
        eventOutcome: opt<String>(json, 'event_outcome'),
        refundedCents: centsFrom(json, 'refunded_cents'),
        paymentStatus: req<String>(json, 'payment_status'),
        orderStatus: req<String>(json, 'order_status'),
      );
}

/// A courier label (`ShipmentResponse`); [isTest] for local contract bookings.
class Shipment {
  const Shipment({
    required this.id,
    required this.orderId,
    required this.provider,
    required this.status,
    required this.isTest,
    required this.createdAt,
    this.serviceName,
    this.labelReference,
    this.trackingNumber,
  });

  final String id;
  final String orderId;
  final String provider;
  final String? serviceName;
  final String? labelReference;
  final String? trackingNumber;
  final String status;
  final bool isTest;
  final DateTime createdAt;

  factory Shipment.fromJson(Map<String, dynamic> json) => Shipment(
        id: req<String>(json, 'id'),
        orderId: req<String>(json, 'order_id'),
        provider: req<String>(json, 'provider'),
        serviceName: opt<String>(json, 'service_name'),
        labelReference: opt<String>(json, 'label_reference'),
        trackingNumber: opt<String>(json, 'tracking_number'),
        status: req<String>(json, 'status'),
        isTest: req<bool>(json, 'is_test'),
        createdAt: reqDate(json, 'created_at'),
      );
}
