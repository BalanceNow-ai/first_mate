class Vessel {
  final String id;
  final String userId;
  final String name;
  final String make;
  final String model;
  final int? year;
  final String? hullMaterial;
  final double? lengthFt;
  final String? engineType;
  final String? engineMake;
  final String? engineModel;
  final String? imageUrl;
  final bool isPrimary;
  final DateTime createdAt;

  Vessel({
    required this.id,
    required this.userId,
    required this.name,
    required this.make,
    required this.model,
    this.year,
    this.hullMaterial,
    this.lengthFt,
    this.engineType,
    this.engineMake,
    this.engineModel,
    this.imageUrl,
    this.isPrimary = false,
    required this.createdAt,
  });

  factory Vessel.fromJson(Map<String, dynamic> json) {
    return Vessel(
      id: json['id'] as String,
      userId: json['user_id'] as String,
      name: json['name'] as String,
      make: json['make'] as String,
      model: json['model'] as String,
      year: json['year'] as int?,
      hullMaterial: json['hull_material'] as String?,
      lengthFt: (json['length_ft'] as num?)?.toDouble(),
      engineType: json['engine_type'] as String?,
      engineMake: json['engine_make'] as String?,
      engineModel: json['engine_model'] as String?,
      imageUrl: json['image_url'] as String?,
      isPrimary: json['is_primary'] as bool? ?? false,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }

  Map<String, dynamic> toJson() => {
        'name': name,
        'make': make,
        'model': model,
        if (year != null) 'year': year,
        if (hullMaterial != null) 'hull_material': hullMaterial,
        if (lengthFt != null) 'length_ft': lengthFt,
        if (engineType != null) 'engine_type': engineType,
        if (engineMake != null) 'engine_make': engineMake,
        if (engineModel != null) 'engine_model': engineModel,
        if (imageUrl != null) 'image_url': imageUrl,
        'is_primary': isPrimary,
      };

  Vessel copyWith({
    String? name,
    String? make,
    String? model,
    int? year,
    String? hullMaterial,
    double? lengthFt,
    String? engineType,
    String? engineMake,
    String? engineModel,
    String? imageUrl,
    bool? isPrimary,
  }) {
    return Vessel(
      id: id,
      userId: userId,
      name: name ?? this.name,
      make: make ?? this.make,
      model: model ?? this.model,
      year: year ?? this.year,
      hullMaterial: hullMaterial ?? this.hullMaterial,
      lengthFt: lengthFt ?? this.lengthFt,
      engineType: engineType ?? this.engineType,
      engineMake: engineMake ?? this.engineMake,
      engineModel: engineModel ?? this.engineModel,
      imageUrl: imageUrl ?? this.imageUrl,
      isPrimary: isPrimary ?? this.isPrimary,
      createdAt: createdAt,
    );
  }
}
