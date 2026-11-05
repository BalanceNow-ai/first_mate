-- pg_dump --schema-only of a database created by Base.metadata.create_all() at main@49877e2
CREATE TABLE public.ai_conversations (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    vessel_id uuid,
    messages jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

CREATE TABLE public.cart_items (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    product_id uuid NOT NULL,
    quantity integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.checklist_items (
    id uuid NOT NULL,
    checklist_id uuid NOT NULL,
    system character varying NOT NULL,
    item_name character varying NOT NULL,
    description text,
    quantity integer NOT NULL,
    product_id uuid,
    is_checked boolean NOT NULL
);

CREATE TABLE public.crew_points (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    points_balance integer NOT NULL,
    tier character varying NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

CREATE TABLE public.crew_team_members (
    team_id uuid NOT NULL,
    user_id uuid NOT NULL,
    joined_at timestamp with time zone NOT NULL
);

CREATE TABLE public.crew_teams (
    id uuid NOT NULL,
    name character varying NOT NULL,
    created_by uuid NOT NULL,
    crew_wallet_balance integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.helm_dash_deliveries (
    id uuid NOT NULL,
    order_id uuid NOT NULL,
    status character varying NOT NULL,
    pickup_location jsonb,
    delivery_coordinates jsonb NOT NULL,
    delivery_location_name character varying,
    nautical_miles numeric(6,2),
    delivery_fee numeric(10,2) NOT NULL,
    estimated_delivery_minutes integer,
    operator_id uuid,
    operator_name character varying,
    notes text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

CREATE TABLE public.order_items (
    id uuid NOT NULL,
    order_id uuid NOT NULL,
    product_id uuid NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(10,2) NOT NULL
);

CREATE TABLE public.orders (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    status character varying NOT NULL,
    subtotal numeric(10,2) NOT NULL,
    shipping_cost numeric(10,2) NOT NULL,
    total numeric(10,2) NOT NULL,
    stripe_payment_intent_id character varying,
    delivery_type character varying,
    shipping_address jsonb,
    helm_dash_coordinates jsonb,
    tracking_number character varying,
    courier character varying,
    notes text,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.product_compatibility (
    id uuid NOT NULL,
    product_id uuid NOT NULL,
    vessel_make character varying,
    vessel_model character varying,
    year_from integer,
    year_to integer,
    engine_make character varying,
    engine_model character varying,
    notes text
);

CREATE TABLE public.products (
    id uuid NOT NULL,
    sku character varying NOT NULL,
    name character varying NOT NULL,
    description text,
    brand character varying,
    category character varying NOT NULL,
    sub_category character varying,
    price numeric(10,2) NOT NULL,
    sale_price numeric(10,2),
    cost_price numeric(10,2),
    stock_quantity integer NOT NULL,
    weight_grams integer,
    images jsonb,
    specifications jsonb,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.rag_documents (
    id uuid NOT NULL,
    agent_domain character varying NOT NULL,
    source character varying NOT NULL,
    content text NOT NULL,
    embedding public.vector(1536),
    metadata jsonb,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.users (
    id uuid NOT NULL,
    email character varying NOT NULL,
    full_name character varying,
    phone character varying,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.vessels (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    nickname character varying NOT NULL,
    hin character varying,
    make character varying NOT NULL,
    model character varying NOT NULL,
    year integer NOT NULL,
    hull_type character varying,
    length_ft integer,
    primary_use character varying,
    engine_make character varying,
    engine_model character varying,
    engine_serial character varying,
    engine_hours integer,
    is_primary boolean NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.voyage_checklists (
    id uuid NOT NULL,
    vessel_id uuid NOT NULL,
    tier character varying NOT NULL,
    name character varying NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.ai_conversations
    ADD CONSTRAINT ai_conversations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.checklist_items
    ADD CONSTRAINT checklist_items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.crew_points
    ADD CONSTRAINT crew_points_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.crew_team_members
    ADD CONSTRAINT crew_team_members_pkey PRIMARY KEY (team_id, user_id);

ALTER TABLE ONLY public.crew_teams
    ADD CONSTRAINT crew_teams_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.helm_dash_deliveries
    ADD CONSTRAINT helm_dash_deliveries_order_id_key UNIQUE (order_id);

ALTER TABLE ONLY public.helm_dash_deliveries
    ADD CONSTRAINT helm_dash_deliveries_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.product_compatibility
    ADD CONSTRAINT product_compatibility_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.rag_documents
    ADD CONSTRAINT rag_documents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.voyage_checklists
    ADD CONSTRAINT voyage_checklists_pkey PRIMARY KEY (id);

CREATE INDEX ix_ai_conversations_user_id ON public.ai_conversations USING btree (user_id);

CREATE INDEX ix_cart_items_user_id ON public.cart_items USING btree (user_id);

CREATE UNIQUE INDEX ix_crew_points_user_id ON public.crew_points USING btree (user_id);

CREATE INDEX ix_orders_user_id ON public.orders USING btree (user_id);

CREATE INDEX ix_products_brand ON public.products USING btree (brand);

CREATE INDEX ix_products_category ON public.products USING btree (category);

CREATE UNIQUE INDEX ix_products_sku ON public.products USING btree (sku);

CREATE INDEX ix_rag_documents_agent_domain ON public.rag_documents USING btree (agent_domain);

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);

CREATE INDEX ix_vessels_user_id ON public.vessels USING btree (user_id);

ALTER TABLE ONLY public.ai_conversations
    ADD CONSTRAINT ai_conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.ai_conversations
    ADD CONSTRAINT ai_conversations_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES public.vessels(id);

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.checklist_items
    ADD CONSTRAINT checklist_items_checklist_id_fkey FOREIGN KEY (checklist_id) REFERENCES public.voyage_checklists(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.checklist_items
    ADD CONSTRAINT checklist_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);

ALTER TABLE ONLY public.crew_points
    ADD CONSTRAINT crew_points_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.crew_team_members
    ADD CONSTRAINT crew_team_members_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.crew_teams(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.crew_team_members
    ADD CONSTRAINT crew_team_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.crew_teams
    ADD CONSTRAINT crew_teams_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.helm_dash_deliveries
    ADD CONSTRAINT helm_dash_deliveries_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id);

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.order_items
    ADD CONSTRAINT order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.product_compatibility
    ADD CONSTRAINT product_compatibility_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.voyage_checklists
    ADD CONSTRAINT voyage_checklists_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES public.vessels(id) ON DELETE CASCADE;
