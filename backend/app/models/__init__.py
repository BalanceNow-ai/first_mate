"""SQLAlchemy models for the Helm platform (import all for metadata registration)."""

from app.models.ai import AIConversation, KnowledgeSource, RAGDocument
from app.models.boat_db import (
    BoatModel,
    EquipmentCategory,
    Manufacturer,
    ModelYear,
    OEMEquipment,
)
from app.models.cart import CartItem
from app.models.checklist import ChecklistItem, VoyageChecklist
from app.models.helm_dash import (
    DeliveryLocationUpdate,
    DeliveryOperator,
    DeliveryStatusEvent,
    HelmDashDelivery,
    OperatingArea,
    OperatorPayout,
)
from app.models.loyalty import (
    CrewInvite,
    CrewPoints,
    CrewTeam,
    CrewTeamMember,
    DiscountEntitlement,
    ExperienceRedemption,
    PointsTransaction,
)
from app.models.notifications import NotificationOutbox, NotificationPreference, PushDevice
from app.models.ops import AuditLog, WorkerHeartbeat
from app.models.order import Order, OrderItem, PaymentEvent, StockReservation
from app.models.product import Product, ProductCompatibility
from app.models.shipping import CourierShipment, DeliveryQuote
from app.models.user import User
from app.models.vessel import (
    EquipmentVerificationRequest,
    ServiceRecord,
    ServiceReminder,
    Vessel,
    VesselEquipment,
)

__all__ = [
    "AIConversation", "AuditLog", "BoatModel", "CartItem", "ChecklistItem", "CourierShipment",
    "CrewInvite", "CrewPoints", "CrewTeam", "CrewTeamMember", "DeliveryLocationUpdate",
    "DeliveryOperator", "DeliveryQuote", "DeliveryStatusEvent", "DiscountEntitlement",
    "EquipmentCategory", "EquipmentVerificationRequest", "ExperienceRedemption",
    "HelmDashDelivery", "KnowledgeSource", "Manufacturer", "ModelYear", "NotificationOutbox",
    "NotificationPreference", "OEMEquipment", "OperatingArea", "OperatorPayout", "Order",
    "OrderItem", "PaymentEvent", "PointsTransaction", "Product", "ProductCompatibility",
    "PushDevice", "RAGDocument", "ServiceRecord", "ServiceReminder", "StockReservation", "User",
    "Vessel", "VesselEquipment", "VoyageChecklist", "WorkerHeartbeat",
]
