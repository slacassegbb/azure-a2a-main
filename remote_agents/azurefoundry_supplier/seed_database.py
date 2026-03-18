"""
Supplier Database Seed Script.
Creates tables and populates with synthetic product data across multiple industries.
Includes products inspired by MacPapers.com catalog + industrial, office, and food service supplies.
Auto-runs on agent startup if tables are empty.
"""
import asyncio
import os
import logging

logger = logging.getLogger(__name__)

# ─── Schema DDL ──────────────────────────────────────────────────────────────

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS supplier_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    parent_category_id INTEGER REFERENCES supplier_categories(id),
    description TEXT
);

CREATE TABLE IF NOT EXISTS supplier_manufacturers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    website VARCHAR(255),
    country VARCHAR(100),
    lead_time_days_min INTEGER,
    lead_time_days_max INTEGER
);

CREATE TABLE IF NOT EXISTS supplier_products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category_id INTEGER REFERENCES supplier_categories(id),
    manufacturer_id INTEGER REFERENCES supplier_manufacturers(id),
    unit_price DECIMAL(10,2),
    unit_of_measure VARCHAR(50),
    weight_lbs DECIMAL(8,2),
    dimensions VARCHAR(100),
    stock_status VARCHAR(20) DEFAULT 'in_stock',
    stock_quantity INTEGER DEFAULT 0,
    lead_time_days INTEGER,
    minimum_order_quantity INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    tags TEXT[],
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supplier_price_tiers (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES supplier_products(id),
    min_quantity INTEGER NOT NULL,
    max_quantity INTEGER,
    unit_price DECIMAL(10,2) NOT NULL,
    discount_percent DECIMAL(5,2)
);

CREATE TABLE IF NOT EXISTS supplier_product_relations (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES supplier_products(id),
    related_product_id INTEGER REFERENCES supplier_products(id),
    relation_type VARCHAR(30) NOT NULL,
    relevance_score DECIMAL(3,2) DEFAULT 0.5
);

CREATE INDEX IF NOT EXISTS idx_supplier_products_sku ON supplier_products(sku);
CREATE INDEX IF NOT EXISTS idx_supplier_products_category ON supplier_products(category_id);
CREATE INDEX IF NOT EXISTS idx_supplier_products_manufacturer ON supplier_products(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_supplier_products_status ON supplier_products(stock_status);
CREATE INDEX IF NOT EXISTS idx_supplier_products_active ON supplier_products(is_active);
CREATE INDEX IF NOT EXISTS idx_supplier_price_tiers_product ON supplier_price_tiers(product_id);
CREATE INDEX IF NOT EXISTS idx_supplier_relations_product ON supplier_product_relations(product_id);
CREATE INDEX IF NOT EXISTS idx_supplier_relations_related ON supplier_product_relations(related_product_id);
"""

# ─── Seed Data ───────────────────────────────────────────────────────────────

CATEGORIES = [
    # id, name, parent_id, description
    (1, "Fine Paper", None, "Premium papers and specialty stocks for printing and publishing"),
    (2, "Bond Paper", 1, "High-quality bond paper for letterheads, forms, and documents"),
    (3, "Cardstock", 1, "Heavy-weight paper for cards, covers, and signage"),
    (4, "Coated Paper", 1, "Glossy and matte coated papers for high-quality printing"),
    (5, "Uncoated Paper", 1, "Natural uncoated papers for books, flyers, and general printing"),
    (6, "Specialty Paper", 1, "Textured, colored, and specialty papers for unique applications"),
    (7, "Packaging", None, "Boxes, mailers, wrapping, and protective packaging materials"),
    (8, "Corrugated Boxes", 7, "Single and double-wall corrugated shipping boxes"),
    (9, "Mailers & Envelopes", 7, "Padded mailers, poly mailers, and shipping envelopes"),
    (10, "Protective Packaging", 7, "Bubble wrap, foam, packing peanuts, and void fill"),
    (11, "Stretch Film & Tape", 7, "Pallet wrap, stretch film, and packaging tape"),
    (12, "Wide Format & Graphics", None, "Large-format printing substrates and media"),
    (13, "Vinyl & Banner", 12, "Vinyl rolls, banner materials for signage and displays"),
    (14, "Canvas & Fine Art", 12, "Canvas rolls and fine art printing media"),
    (15, "Engineering & Blueprint", 12, "Bond rolls and media for CAD and architectural printing"),
    (16, "Envelopes", None, "Standard, catalog, and custom envelopes for mailing"),
    (17, "Standard Envelopes", 16, "#10 business envelopes, window and plain"),
    (18, "Catalog & Booklet", 16, "Large-format envelopes for catalogs and documents"),
    (19, "Custom & Specialty", 16, "Custom-printed and specialty envelopes"),
    (20, "Facility Supplies", None, "Janitorial, sanitation, and facility maintenance products"),
    (21, "Paper Towels & Tissue", 20, "Towel rolls, folded towels, toilet tissue, and facial tissue"),
    (22, "Trash & Waste", 20, "Trash bags, liners, and waste receptacles"),
    (23, "Cleaning Chemicals", 20, "Cleaners, disinfectants, and sanitizers"),
    (24, "Safety & PPE", 20, "Gloves, masks, eye protection, and safety equipment"),
    (25, "Industrial Supplies", None, "Fasteners, adhesives, abrasives, and tools"),
    (26, "Fasteners", 25, "Bolts, screws, nuts, washers, and anchors"),
    (27, "Adhesives & Sealants", 25, "Tapes, glues, epoxies, and sealants"),
    (28, "Abrasives", 25, "Sandpaper, grinding wheels, and polishing compounds"),
    (29, "Hand Tools", 25, "Wrenches, screwdrivers, pliers, and measuring tools"),
    (30, "Office Supplies", None, "Paper, toner, binders, labels, and desk accessories"),
    (31, "Copy & Printer Paper", 30, "Multipurpose, copy, and laser printer paper"),
    (32, "Toner & Ink", 30, "Toner cartridges, ink cartridges, and ribbons"),
    (33, "Binders & Filing", 30, "Ring binders, file folders, and storage boxes"),
    (34, "Labels & Stickers", 30, "Address labels, shipping labels, and label makers"),
    (35, "Food Service", None, "Disposable containers, cups, utensils, and food packaging"),
    (36, "Disposable Containers", 35, "Takeout containers, clamshells, and deli containers"),
    (37, "Cups & Lids", 35, "Hot cups, cold cups, lids, and sleeves"),
    (38, "Napkins & Tissue", 35, "Napkins, placemats, and food service tissue"),
    (39, "Utensils & Cutlery", 35, "Forks, knives, spoons, and combo packs"),
    (40, "Food Wrap & Foil", 35, "Plastic wrap, aluminum foil, and wax paper"),
]

MANUFACTURERS = [
    # id, name, website, country, lead_min, lead_max
    (1, "Domtar", "https://www.domtar.com", "USA", 3, 10),
    (2, "International Paper", "https://www.internationalpaper.com", "USA", 3, 12),
    (3, "3M", "https://www.3m.com", "USA", 2, 7),
    (4, "Hammermill", "https://www.hammermill.com", "USA", 2, 8),
    (5, "GP Pro (Georgia-Pacific)", "https://www.gppro.com", "USA", 3, 10),
    (6, "Avery Dennison", "https://www.averydennison.com", "USA", 2, 7),
    (7, "Mohawk Fine Papers", "https://www.mohawkconnects.com", "USA", 5, 15),
    (8, "Neenah Paper", "https://www.neenahpaper.com", "USA", 4, 12),
    (9, "Sappi", "https://www.sappi.com", "South Africa", 7, 21),
    (10, "Uline", "https://www.uline.com", "USA", 1, 3),
    (11, "Sealed Air", "https://www.sealedair.com", "USA", 3, 10),
    (12, "Berry Global", "https://www.berryglobal.com", "USA", 5, 14),
    (13, "Dart Container", "https://www.dartcontainer.com", "USA", 3, 8),
    (14, "Solo Cup (Dart)", "https://www.dartcontainer.com", "USA", 3, 8),
    (15, "HP Inc.", "https://www.hp.com", "USA", 2, 5),
    (16, "Canon", "https://www.usa.canon.com", "Japan", 3, 10),
    (17, "Epson", "https://www.epson.com", "Japan", 3, 10),
    (18, "Stanley Black & Decker", "https://www.stanleyblackanddecker.com", "USA", 2, 7),
    (19, "Norton (Saint-Gobain)", "https://www.nortonabrasives.com", "France", 5, 14),
    (20, "Fastenal", "https://www.fastenal.com", "USA", 1, 5),
    (21, "MacPapers & Packaging", "https://www.macpapers.com", "USA", 2, 8),
    (22, "Boise Paper", "https://www.boisepaper.com", "USA", 3, 9),
    (23, "Clearwater Paper", "https://www.clearwaterpaper.com", "USA", 4, 12),
    (24, "Pactiv Evergreen", "https://www.pactivevergreen.com", "USA", 3, 10),
    (25, "Kimberly-Clark", "https://www.kimberly-clark.com", "USA", 2, 7),
]

# Products: (sku, name, description, category_id, manufacturer_id, unit_price, unit_of_measure, weight_lbs, dimensions, stock_status, stock_quantity, lead_time_days, min_order_qty, tags)
PRODUCTS = [
    # ── Fine Paper / Bond ────
    ("FP-BOND-001", "Domtar Husky Offset 20lb Bond", "High-brightness 20lb bond paper, ideal for letterheads and business forms. 92 brightness, acid-free.", 2, 1, 8.50, "ream", 5.0, "8.5x11", "in_stock", 5000, 3, 1, ["bond", "20lb", "acid-free", "FSC-certified"]),
    ("FP-BOND-002", "Hammermill Fore MP 24lb Bond", "Premium multipurpose 24lb bond, ColorLok technology for vivid colors. 96 brightness.", 2, 4, 12.75, "ream", 6.2, "8.5x11", "in_stock", 3200, 2, 1, ["bond", "24lb", "ColorLok", "premium"]),
    ("FP-BOND-003", "Domtar Lynx Opaque 60lb Text", "Ultra-smooth opaque text weight paper for high-end printing. 96 brightness.", 2, 1, 24.50, "ream", 8.5, "8.5x11", "in_stock", 1200, 5, 1, ["bond", "60lb", "opaque", "premium"]),
    ("FP-BOND-004", "International Paper Accent Opaque 70lb Text", "Smooth finish opaque paper, excellent for two-sided printing. 97 brightness.", 2, 2, 28.90, "ream", 9.1, "8.5x11", "low_stock", 250, 7, 1, ["bond", "70lb", "opaque", "two-sided"]),
    ("FP-BOND-005", "MacPapers Premium Bond 28lb", "MacPapers house brand premium bond paper, excellent for professional correspondence.", 2, 21, 15.25, "ream", 7.0, "8.5x11", "in_stock", 4000, 2, 1, ["bond", "28lb", "premium", "house-brand"]),

    # ── Fine Paper / Cardstock ────
    ("FP-CARD-001", "Domtar Cougar 65lb Cover", "Smooth white cardstock for brochures, report covers, and postcards. FSC certified.", 3, 1, 22.00, "ream", 12.0, "8.5x11", "in_stock", 2000, 4, 1, ["cardstock", "65lb", "FSC-certified", "smooth"]),
    ("FP-CARD-002", "Neenah Exact Index 110lb", "Heavyweight index cardstock for tabs, dividers, and menus. Bright white.", 3, 8, 32.50, "ream", 16.0, "8.5x11", "in_stock", 800, 5, 1, ["cardstock", "110lb", "heavyweight", "index"]),
    ("FP-CARD-003", "Mohawk Superfine 100lb Cover", "Ultra-premium eggshell finish cardstock for luxury printing applications.", 3, 7, 65.00, "ream", 14.5, "8.5x11", "in_stock", 400, 8, 1, ["cardstock", "100lb", "eggshell", "luxury", "premium"]),
    ("FP-CARD-004", "MacPapers ColorMax 80lb Cover", "Vibrant color cardstock available in 12 colors. Great for POP displays.", 3, 21, 18.75, "ream", 11.0, "8.5x11", "in_stock", 3000, 3, 1, ["cardstock", "80lb", "colored", "POP"]),

    # ── Fine Paper / Coated ────
    ("FP-COAT-001", "Sappi McCoy Silk 100lb Text", "Premium silk-coated paper with exceptional ink holdout. For catalogs and magazines.", 4, 9, 42.00, "ream", 13.0, "8.5x11", "in_stock", 1500, 10, 1, ["coated", "silk", "100lb", "premium"]),
    ("FP-COAT-002", "Sappi Flo Gloss 80lb Text", "High-gloss coated paper for vibrant photo reproduction and brochures.", 4, 9, 35.50, "ream", 10.5, "8.5x11", "in_stock", 1800, 10, 1, ["coated", "gloss", "80lb"]),
    ("FP-COAT-003", "International Paper Accent Opaque Digital Gloss 100lb Cover", "Digital-optimized gloss cover for high-speed digital presses.", 4, 2, 48.00, "ream", 14.0, "8.5x11", "low_stock", 300, 12, 1, ["coated", "gloss", "digital", "100lb"]),

    # ── Fine Paper / Uncoated ────
    ("FP-UNCO-001", "Domtar EarthChoice 50lb Offset", "100% recycled uncoated offset paper. FSC certified, Green Seal approved.", 5, 1, 14.00, "ream", 7.5, "8.5x11", "in_stock", 6000, 3, 1, ["uncoated", "recycled", "FSC-certified", "green"]),
    ("FP-UNCO-002", "Mohawk Via Vellum 70lb Text", "Luxurious vellum finish uncoated paper for stationery and invitations.", 5, 7, 38.00, "ream", 9.0, "8.5x11", "in_stock", 600, 7, 1, ["uncoated", "vellum", "luxury", "stationery"]),

    # ── Fine Paper / Specialty ────
    ("FP-SPEC-001", "Neenah Classic Linen 80lb Cover", "Linen-textured specialty cover in natural white for formal invitations.", 6, 8, 55.00, "ream", 11.5, "8.5x11", "in_stock", 500, 6, 1, ["specialty", "linen", "textured", "formal"]),
    ("FP-SPEC-002", "Mohawk Loop Antique Vellum 80lb Text", "100% PCW recycled with distinctive antique vellum texture.", 6, 7, 45.00, "ream", 10.0, "8.5x11", "in_stock", 350, 8, 1, ["specialty", "recycled", "antique", "textured"]),

    # ── Packaging / Corrugated Boxes ────
    ("PK-BOX-001", "Uline Standard Shipping Box 12x12x12", "Single-wall 32 ECT corrugated shipping box, kraft brown.", 8, 10, 1.85, "each", 1.2, "12x12x12", "in_stock", 25000, 1, 25, ["corrugated", "shipping", "32ECT", "standard"]),
    ("PK-BOX-002", "Uline Standard Shipping Box 18x18x18", "Single-wall 32 ECT corrugated box for medium items.", 8, 10, 2.65, "each", 1.8, "18x18x18", "in_stock", 18000, 1, 25, ["corrugated", "shipping", "32ECT"]),
    ("PK-BOX-003", "Uline Heavy-Duty Box 24x24x24", "Double-wall 48 ECT heavy-duty box for fragile or heavy items.", 8, 10, 5.95, "each", 3.5, "24x24x24", "in_stock", 8000, 2, 10, ["corrugated", "heavy-duty", "48ECT", "double-wall"]),
    ("PK-BOX-004", "International Paper Boxes 16x12x8", "Standard RSC box for e-commerce and retail shipping.", 8, 2, 2.10, "each", 1.0, "16x12x8", "in_stock", 15000, 3, 25, ["corrugated", "e-commerce", "RSC"]),
    ("PK-BOX-005", "MacPapers Custom Print Box 12x10x6", "White corrugated box with custom print capability. MOQ 500.", 8, 21, 3.50, "each", 0.9, "12x10x6", "in_stock", 5000, 5, 500, ["corrugated", "custom-print", "white", "branded"]),

    # ── Packaging / Mailers ────
    ("PK-MAIL-001", "Sealed Air Bubble Mailer #0 (6x10)", "Self-seal kraft bubble mailer for small items and documents.", 9, 11, 0.45, "each", 0.1, "6x10", "in_stock", 50000, 2, 25, ["bubble-mailer", "self-seal", "kraft"]),
    ("PK-MAIL-002", "Uline Poly Mailer 10x13", "Tear-proof polyethylene mailer, white, self-adhesive closure.", 9, 10, 0.22, "each", 0.05, "10x13", "in_stock", 100000, 1, 100, ["poly-mailer", "tear-proof", "white"]),
    ("PK-MAIL-003", "Uline Rigid Mailer 9x11.5", "Stay-flat rigid board mailer for photos and documents.", 9, 10, 1.15, "each", 0.3, "9x11.5", "in_stock", 12000, 1, 25, ["rigid-mailer", "stay-flat"]),

    # ── Packaging / Protective ────
    ("PK-PROT-001", "Sealed Air Bubble Wrap 12in x 250ft", "Standard 3/16in small bubble cushioning roll.", 10, 11, 32.00, "roll", 8.0, "12x250ft", "in_stock", 2000, 3, 1, ["bubble-wrap", "cushioning", "protective"]),
    ("PK-PROT-002", "Sealed Air Instapak Quick RT #40", "Foam-in-place packaging for custom cushioning around irregular shapes.", 10, 11, 89.00, "case", 15.0, "18x24", "in_stock", 500, 5, 1, ["foam", "instapak", "custom-cushioning"]),
    ("PK-PROT-003", "Uline Packing Peanuts (14 cu ft bag)", "Anti-static polystyrene packing peanuts for void fill.", 10, 10, 28.00, "bag", 3.0, "14 cu ft", "in_stock", 3000, 1, 1, ["packing-peanuts", "void-fill", "anti-static"]),

    # ── Packaging / Stretch Film & Tape ────
    ("PK-FILM-001", "Berry Global Machine Stretch Film 20in x 5000ft", "80-gauge machine-grade stretch film for pallet wrapping.", 11, 12, 42.00, "roll", 25.0, "20x5000ft", "in_stock", 3000, 5, 1, ["stretch-film", "machine-grade", "pallet-wrap"]),
    ("PK-FILM-002", "Uline Hand Stretch Film 18in x 1500ft", "70-gauge hand stretch wrap, easy-to-use for manual application.", 11, 10, 18.50, "roll", 8.5, "18x1500ft", "in_stock", 8000, 1, 4, ["stretch-film", "hand-wrap", "manual"]),
    ("PK-TAPE-001", "3M Scotch 375 Packaging Tape 2in x 110yd", "High-performance hot melt adhesive packaging tape, clear.", 11, 3, 4.25, "roll", 0.5, "2x110yd", "in_stock", 30000, 2, 36, ["tape", "packaging", "hot-melt", "clear"]),
    ("PK-TAPE-002", "3M Scotch 373 Packaging Tape 3in x 110yd", "Premium polypropylene tape for heavy-duty sealing, tan.", 11, 3, 6.50, "roll", 0.7, "3x110yd", "in_stock", 20000, 2, 24, ["tape", "packaging", "heavy-duty", "tan"]),

    # ── Wide Format / Vinyl & Banner ────
    ("WF-VIN-001", "MacPapers Premium Vinyl 54in x 150ft", "Calendered matte white vinyl for indoor/outdoor signage. 3.4 mil.", 13, 21, 185.00, "roll", 35.0, "54x150ft", "in_stock", 300, 3, 1, ["vinyl", "matte", "signage", "indoor-outdoor"]),
    ("WF-VIN-002", "MacPapers Glossy Vinyl 54in x 150ft", "High-gloss calendered vinyl for vibrant vehicle wraps and graphics.", 13, 21, 195.00, "roll", 36.0, "54x150ft", "in_stock", 250, 3, 1, ["vinyl", "gloss", "vehicle-wrap"]),
    ("WF-BAN-001", "MacPapers Blockout Banner 13oz 54in x 164ft", "Scrim vinyl banner material for double-sided printing.", 13, 21, 165.00, "roll", 45.0, "54x164ft", "in_stock", 400, 4, 1, ["banner", "blockout", "double-sided", "13oz"]),

    # ── Wide Format / Canvas ────
    ("WF-CAN-001", "Epson Premium Canvas Satin 44in x 40ft", "Bright white poly-cotton canvas with satin finish for fine art.", 14, 17, 125.00, "roll", 8.0, "44x40ft", "in_stock", 200, 5, 1, ["canvas", "satin", "fine-art", "poly-cotton"]),
    ("WF-CAN-002", "HP Everyday Matte Canvas 42in x 75ft", "Cost-effective matte canvas for photo and art reproduction.", 14, 15, 98.00, "roll", 10.0, "42x75ft", "in_stock", 350, 3, 1, ["canvas", "matte", "photo", "everyday"]),

    # ── Wide Format / Engineering ────
    ("WF-ENG-001", "MacPapers CAD Bond 20lb 36in x 500ft", "Bright white bond roll for CAD plotters and blueprints.", 15, 21, 45.00, "roll", 20.0, "36x500ft", "in_stock", 1500, 2, 1, ["CAD", "bond", "plotter", "blueprint"]),

    # ── Envelopes / Standard ────
    ("ENV-STD-001", "MacPapers #10 Regular Envelope (500ct)", "Standard #10 business envelope, 24lb white wove, gummed flap.", 17, 21, 28.00, "box", 5.5, "4.125x9.5", "in_stock", 10000, 2, 1, ["envelope", "#10", "business", "white"]),
    ("ENV-STD-002", "MacPapers #10 Window Envelope (500ct)", "#10 envelope with single left window for forms and invoices.", 17, 21, 32.00, "box", 5.8, "4.125x9.5", "in_stock", 8000, 2, 1, ["envelope", "#10", "window", "invoice"]),
    ("ENV-STD-003", "International Paper #10 Security Envelope (500ct)", "Blue-lined security tint #10 envelope for confidential mail.", 17, 2, 35.00, "box", 5.7, "4.125x9.5", "in_stock", 6000, 3, 1, ["envelope", "#10", "security", "confidential"]),

    # ── Envelopes / Catalog ────
    ("ENV-CAT-001", "MacPapers 9x12 Catalog Envelope (250ct)", "Open-end catalog envelope, 28lb kraft, clasp closure.", 18, 21, 38.00, "box", 8.0, "9x12", "in_stock", 4000, 3, 1, ["envelope", "catalog", "9x12", "kraft"]),
    ("ENV-CAT-002", "MacPapers 10x13 Catalog Envelope (250ct)", "Open-end catalog envelope, 28lb white, peel & seal.", 18, 21, 42.00, "box", 9.0, "10x13", "in_stock", 3500, 3, 1, ["envelope", "catalog", "10x13", "peel-seal"]),

    # ── Facility / Paper Towels & Tissue ────
    ("FS-TOW-001", "GP Pro enMotion 10in Recycled Towel Roll (6ct)", "High-capacity touchless towel roll, 100% recycled fiber.", 21, 5, 72.00, "case", 18.0, "10x800ft", "in_stock", 2000, 3, 1, ["towel", "recycled", "touchless", "high-capacity"]),
    ("FS-TOW-002", "Kimberly-Clark Scott Essential Folded Towel (4000ct)", "Multifold paper towels, white, absorbent.", 21, 25, 45.00, "case", 12.0, "9.2x9.4", "in_stock", 5000, 2, 1, ["towel", "multifold", "white"]),
    ("FS-TIS-001", "GP Pro Angel Soft Professional 2-Ply Toilet Tissue (80 rolls)", "Standard 2-ply toilet tissue, 450 sheets per roll.", 21, 5, 58.00, "case", 22.0, "4.5x4", "in_stock", 4000, 3, 1, ["tissue", "toilet", "2-ply"]),

    # ── Facility / Trash ────
    ("FS-TRH-001", "Berry Global 55-Gallon Drum Liner (100ct)", "Heavy-duty 2-mil black drum liner for industrial waste.", 22, 12, 38.00, "case", 14.0, "38x58", "in_stock", 3000, 5, 1, ["trash-bag", "drum-liner", "heavy-duty", "2-mil"]),
    ("FS-TRH-002", "Uline 33-Gallon Trash Bag 1.5mil (100ct)", "Standard 1.5-mil black trash bag for offices and facilities.", 22, 10, 22.00, "case", 8.0, "33x39", "in_stock", 8000, 1, 1, ["trash-bag", "33-gallon", "office"]),

    # ── Facility / Cleaning ────
    ("FS-CLN-001", "3M All-Purpose Cleaner Concentrate (1 gal)", "Versatile cleaning concentrate, dilutes up to 1:64. Non-toxic.", 23, 3, 18.50, "gallon", 8.5, "1 gallon", "in_stock", 1500, 2, 1, ["cleaner", "concentrate", "all-purpose", "non-toxic"]),
    ("FS-CLN-002", "3M Disinfectant Spray (12 x 19oz)", "Hospital-grade disinfectant spray, kills 99.9% of germs.", 23, 3, 65.00, "case", 16.0, "19oz x 12", "in_stock", 2000, 2, 1, ["disinfectant", "spray", "hospital-grade"]),

    # ── Facility / Safety ────
    ("FS-SAF-001", "3M N95 Particulate Respirator (20ct)", "NIOSH-approved N95 respirator for particulate protection.", 24, 3, 28.00, "box", 0.8, "Standard", "in_stock", 10000, 2, 1, ["N95", "respirator", "NIOSH", "safety"]),
    ("FS-SAF-002", "Berry Global Nitrile Gloves Medium (100ct)", "Powder-free nitrile exam gloves, blue, 4-mil thickness.", 24, 12, 12.50, "box", 1.0, "Medium", "in_stock", 20000, 3, 1, ["gloves", "nitrile", "powder-free", "exam"]),
    ("FS-SAF-003", "3M Safety Glasses SecureFit 400", "Anti-fog, anti-scratch polycarbonate safety glasses.", 24, 3, 8.75, "each", 0.1, "Standard", "in_stock", 5000, 2, 1, ["safety-glasses", "anti-fog", "polycarbonate"]),

    # ── Industrial / Fasteners ────
    ("IN-FST-001", "Fastenal Grade 8 Hex Bolt 1/2-13 x 2in (25ct)", "High-strength Grade 8 hex bolt, zinc yellow finish.", 26, 20, 18.50, "box", 3.0, "1/2-13 x 2in", "in_stock", 5000, 1, 1, ["fastener", "bolt", "grade-8", "hex"]),
    ("IN-FST-002", "Fastenal Stainless Steel Machine Screw #10-32 x 1in (100ct)", "316 stainless steel Phillips machine screw for corrosion resistance.", 26, 20, 14.00, "box", 1.5, "#10-32 x 1in", "in_stock", 8000, 1, 1, ["fastener", "screw", "stainless", "machine"]),
    ("IN-FST-003", "Fastenal Nylon Lock Nut 3/8-16 (50ct)", "Grade C prevailing torque lock nut, zinc plated.", 26, 20, 8.50, "box", 1.2, "3/8-16", "in_stock", 12000, 1, 1, ["fastener", "nut", "lock-nut", "nylon"]),

    # ── Industrial / Adhesives ────
    ("IN-ADH-001", "3M Super 77 Multipurpose Spray Adhesive (16.75oz)", "Fast-tacking spray adhesive for lightweight materials.", 27, 3, 14.25, "can", 1.2, "16.75oz", "in_stock", 3000, 2, 1, ["adhesive", "spray", "multipurpose"]),
    ("IN-ADH-002", "3M Scotch-Weld Epoxy DP420 (1.25oz)", "Off-white structural epoxy adhesive, high shear strength.", 27, 3, 32.00, "cartridge", 0.3, "1.25oz", "in_stock", 1500, 3, 1, ["adhesive", "epoxy", "structural"]),
    ("IN-ADH-003", "3M VHB Tape 4910 Clear 1in x 36yd", "Very high bond acrylic foam tape for permanent bonding.", 27, 3, 45.00, "roll", 0.5, "1x36yd", "in_stock", 2000, 2, 1, ["tape", "VHB", "acrylic", "permanent"]),

    # ── Industrial / Abrasives ────
    ("IN-ABR-001", "Norton ProSand 9x11 220-Grit (20 sheets)", "Premium aluminum oxide sandpaper for fine finishing.", 28, 19, 12.00, "pack", 0.5, "9x11", "in_stock", 5000, 5, 1, ["sandpaper", "220-grit", "fine", "aluminum-oxide"]),
    ("IN-ABR-002", "Norton Blaze Ceramic Flap Disc 4.5in 80-Grit", "High-performance ceramic flap disc for aggressive material removal.", 28, 19, 8.50, "each", 0.4, "4.5in", "in_stock", 3000, 5, 1, ["flap-disc", "ceramic", "80-grit", "grinding"]),

    # ── Industrial / Hand Tools ────
    ("IN-TOOL-001", "Stanley FatMax 25ft Tape Measure", "Heavy-duty 25ft tape measure with BladeArmor coating.", 29, 18, 24.00, "each", 1.0, "25ft", "in_stock", 2000, 2, 1, ["tape-measure", "25ft", "heavy-duty"]),
    ("IN-TOOL-002", "Stanley 10-Piece Screwdriver Set", "Phillips and slotted screwdriver set with cushion grip handles.", 29, 18, 18.00, "set", 2.5, "Various", "in_stock", 1500, 2, 1, ["screwdriver", "set", "phillips", "slotted"]),

    # ── Office / Copy Paper ────
    ("OF-CPY-001", "Hammermill Copy Plus 20lb (10 reams)", "Everyday copy paper, 92 brightness, 500 sheets per ream.", 31, 4, 52.00, "case", 50.0, "8.5x11", "in_stock", 10000, 2, 1, ["copy-paper", "20lb", "everyday", "bulk"]),
    ("OF-CPY-002", "Boise X-9 Multi-Use Paper 20lb (10 reams)", "Reliable multipurpose paper for copiers, fax, and laser printers.", 31, 22, 48.00, "case", 50.0, "8.5x11", "in_stock", 8000, 3, 1, ["copy-paper", "20lb", "multi-use"]),
    ("OF-CPY-003", "Hammermill Premium Color Copy 28lb (500 sheets)", "Ultra-smooth 100 brightness paper for color laser printing.", 31, 4, 18.50, "ream", 7.5, "8.5x11", "in_stock", 4000, 2, 1, ["copy-paper", "28lb", "color", "premium", "100-bright"]),
    ("OF-CPY-004", "Domtar EarthChoice Office Paper 20lb Recycled", "30% post-consumer recycled office paper, SFI certified.", 31, 1, 55.00, "case", 50.0, "8.5x11", "in_stock", 6000, 3, 1, ["copy-paper", "recycled", "30PCW", "green"]),
    ("OF-CPY-005", "MacPapers Everyday Copy 20lb (10 reams)", "MacPapers house brand everyday copy paper, 92 brightness.", 31, 21, 42.00, "case", 50.0, "8.5x11", "in_stock", 15000, 1, 1, ["copy-paper", "20lb", "value", "house-brand"]),

    # ── Office / Toner ────
    ("OF-TNR-001", "HP 26A Black LaserJet Toner (CF226A)", "Original HP toner cartridge, ~3,100 pages yield.", 32, 15, 89.00, "each", 2.5, "Standard", "in_stock", 1200, 2, 1, ["toner", "HP", "black", "LaserJet"]),
    ("OF-TNR-002", "Canon 055H High-Yield Black Toner", "High-capacity black toner for imageCLASS series, ~7,600 pages.", 32, 16, 115.00, "each", 1.8, "Standard", "in_stock", 600, 3, 1, ["toner", "Canon", "black", "high-yield"]),
    ("OF-TNR-003", "HP 63XL High Yield Tri-Color Ink (F6U63AN)", "High-yield tri-color inkjet cartridge, ~330 pages.", 32, 15, 42.00, "each", 0.3, "Standard", "in_stock", 2000, 2, 1, ["ink", "HP", "tri-color", "high-yield"]),

    # ── Office / Binders ────
    ("OF-BND-001", "Avery Durable View Binder 1in White (12ct)", "White slant-ring binder with clear cover pocket.", 33, 6, 36.00, "case", 12.0, "1in", "in_stock", 3000, 2, 1, ["binder", "1in", "white", "durable"]),
    ("OF-BND-002", "Avery Heavy-Duty View Binder 3in (6ct)", "Extra-durable one-touch EZD ring binder, navy blue.", 33, 6, 48.00, "case", 18.0, "3in", "in_stock", 1500, 3, 1, ["binder", "3in", "heavy-duty", "EZD"]),

    # ── Office / Labels ────
    ("OF-LBL-001", "Avery Easy Peel Address Labels 1x2.625 (3000ct)", "White matte address labels for laser and inkjet printers.", 34, 6, 32.00, "box", 3.0, "1x2.625", "in_stock", 5000, 2, 1, ["label", "address", "easy-peel", "white"]),
    ("OF-LBL-002", "Avery Shipping Labels 2x4 (1000ct)", "TrueBlock white shipping labels, opaque to cover old info.", 34, 6, 28.50, "box", 4.0, "2x4", "in_stock", 4000, 2, 1, ["label", "shipping", "TrueBlock", "opaque"]),

    # ── Food Service / Containers ────
    ("FD-CNT-001", "Dart ClearPac SafeSeal 24oz Container (200ct)", "Crystal-clear hinged-lid tamper-resistant deli container.", 36, 13, 62.00, "case", 10.0, "6.4x2.6", "in_stock", 3000, 3, 1, ["container", "clear", "tamper-resistant", "deli"]),
    ("FD-CNT-002", "Pactiv EarthChoice 9in Clamshell (150ct)", "Compostable MFPP clamshell for hot and cold foods.", 36, 24, 55.00, "case", 8.0, "9x9x3", "in_stock", 2000, 4, 1, ["clamshell", "compostable", "hot-food"]),
    ("FD-CNT-003", "Dart Insulated Foam Container 8oz (1000ct)", "White insulated foam food container for soup and chili.", 36, 13, 48.00, "case", 6.0, "8oz", "in_stock", 5000, 3, 1, ["container", "foam", "insulated", "soup"]),

    # ── Food Service / Cups ────
    ("FD-CUP-001", "Solo Bistro 12oz Hot Cup (1000ct)", "Printed paper hot cup with poly-lined interior.", 37, 14, 65.00, "case", 12.0, "12oz", "in_stock", 4000, 3, 1, ["cup", "hot", "paper", "12oz"]),
    ("FD-CUP-002", "Dart Conex Galaxy 16oz Cold Cup (1000ct)", "Translucent polystyrene cold cup for beverages.", 37, 13, 42.00, "case", 8.0, "16oz", "in_stock", 6000, 3, 1, ["cup", "cold", "translucent", "16oz"]),
    ("FD-CUP-003", "Solo Traveler Dome Lid for 12-16oz (1000ct)", "White dome sip-through lid for hot cups.", 37, 14, 38.00, "case", 5.0, "12-16oz", "in_stock", 8000, 3, 1, ["lid", "dome", "hot-cup", "sip"]),

    # ── Food Service / Napkins ────
    ("FD-NAP-001", "GP Pro Essence Impressions 2-Ply Dinner Napkin (1000ct)", "Premium 2-ply embossed dinner napkin, white.", 38, 5, 42.00, "case", 10.0, "17x17", "in_stock", 3000, 3, 1, ["napkin", "dinner", "2-ply", "premium"]),
    ("FD-NAP-002", "GP Pro MorNap Full-Fold Dispenser Napkin (6000ct)", "Compact full-fold napkin for tabletop dispensers.", 38, 5, 35.00, "case", 14.0, "13x12", "in_stock", 5000, 3, 1, ["napkin", "dispenser", "full-fold"]),

    # ── Food Service / Utensils ────
    ("FD-UTN-001", "Dart Impress Medium-Weight Fork (1000ct)", "White medium-weight polypropylene disposable fork.", 39, 13, 18.00, "case", 5.0, "Standard", "in_stock", 8000, 3, 1, ["fork", "disposable", "medium-weight"]),
    ("FD-UTN-002", "Dart Combo Pack Fork/Knife/Spoon/Napkin (250ct)", "Individually wrapped utensil kit with napkin.", 39, 13, 32.00, "case", 8.0, "Standard", "in_stock", 4000, 3, 1, ["combo-pack", "utensil-kit", "wrapped"]),

    # ── Food Service / Wrap ────
    ("FD-WRP-001", "Berry Global Cling Wrap 18in x 2000ft", "Commercial PVC cling film for food storage.", 40, 12, 24.00, "roll", 5.0, "18x2000ft", "in_stock", 3000, 3, 1, ["cling-wrap", "PVC", "commercial"]),
    ("FD-WRP-002", "Reynolds Wrap Standard Foil 18in x 1000ft", "Standard aluminum foil for food prep and storage.", 40, 12, 55.00, "roll", 12.0, "18x1000ft", "in_stock", 2000, 4, 1, ["aluminum-foil", "standard", "food-prep"]),

    # ── Some backordered / discontinued items for realistic variety ────
    ("FP-BOND-006", "Clearwater Premium Bond 24lb", "Clearwater house brand premium bond, limited availability.", 2, 23, 14.00, "ream", 6.5, "8.5x11", "backordered", 0, 30, 1, ["bond", "24lb", "backordered"]),
    ("PK-BOX-006", "Uline Specialty Moving Box Large", "Large moving box with handles, double-wall construction.", 8, 10, 4.75, "each", 2.5, "24x18x18", "backordered", 0, 14, 10, ["corrugated", "moving", "double-wall", "handles"]),
    ("OF-TNR-004", "Epson 702XL High-Capacity Black Ink", "High-capacity pigment black ink for WorkForce Pro series.", 32, 17, 48.00, "each", 0.2, "Standard", "discontinued", 50, 45, 1, ["ink", "Epson", "black", "discontinued"]),
]

# Price tiers: (product_sku, min_qty, max_qty, unit_price, discount_percent)
PRICE_TIERS = [
    # Bond paper tiers
    ("FP-BOND-001", 1, 9, 8.50, 0), ("FP-BOND-001", 10, 49, 7.65, 10), ("FP-BOND-001", 50, 199, 6.80, 20), ("FP-BOND-001", 200, None, 5.95, 30),
    ("FP-BOND-002", 1, 9, 12.75, 0), ("FP-BOND-002", 10, 49, 11.48, 10), ("FP-BOND-002", 50, None, 10.20, 20),
    ("FP-BOND-005", 1, 9, 15.25, 0), ("FP-BOND-005", 10, 49, 13.73, 10), ("FP-BOND-005", 50, 199, 12.20, 20), ("FP-BOND-005", 200, None, 10.68, 30),
    # Corrugated box tiers
    ("PK-BOX-001", 25, 99, 1.85, 0), ("PK-BOX-001", 100, 499, 1.57, 15), ("PK-BOX-001", 500, 1999, 1.30, 30), ("PK-BOX-001", 2000, None, 1.11, 40),
    ("PK-BOX-002", 25, 99, 2.65, 0), ("PK-BOX-002", 100, 499, 2.25, 15), ("PK-BOX-002", 500, None, 1.86, 30),
    ("PK-BOX-005", 500, 999, 3.50, 0), ("PK-BOX-005", 1000, 4999, 2.98, 15), ("PK-BOX-005", 5000, None, 2.45, 30),
    # Copy paper tiers
    ("OF-CPY-001", 1, 4, 52.00, 0), ("OF-CPY-001", 5, 19, 46.80, 10), ("OF-CPY-001", 20, 49, 41.60, 20), ("OF-CPY-001", 50, None, 36.40, 30),
    ("OF-CPY-005", 1, 4, 42.00, 0), ("OF-CPY-005", 5, 19, 37.80, 10), ("OF-CPY-005", 20, 49, 33.60, 20), ("OF-CPY-005", 50, None, 29.40, 30),
    # Stretch film tiers
    ("PK-FILM-001", 1, 9, 42.00, 0), ("PK-FILM-001", 10, 49, 37.80, 10), ("PK-FILM-001", 50, None, 33.60, 20),
    # Tape tiers
    ("PK-TAPE-001", 36, 71, 4.25, 0), ("PK-TAPE-001", 72, 143, 3.61, 15), ("PK-TAPE-001", 144, None, 2.98, 30),
    # Food service tiers
    ("FD-CUP-001", 1, 4, 65.00, 0), ("FD-CUP-001", 5, 19, 58.50, 10), ("FD-CUP-001", 20, None, 52.00, 20),
    ("FD-CNT-001", 1, 4, 62.00, 0), ("FD-CNT-001", 5, 19, 55.80, 10), ("FD-CNT-001", 20, None, 49.60, 20),
    # Towel tiers
    ("FS-TOW-001", 1, 9, 72.00, 0), ("FS-TOW-001", 10, 49, 64.80, 10), ("FS-TOW-001", 50, None, 57.60, 20),
    # Gloves tiers
    ("FS-SAF-002", 1, 9, 12.50, 0), ("FS-SAF-002", 10, 49, 10.63, 15), ("FS-SAF-002", 50, None, 8.75, 30),
]

# Product relations: (product_sku, related_sku, relation_type, score)
PRODUCT_RELATIONS = [
    # Bond paper alternatives
    ("FP-BOND-001", "FP-BOND-002", "alternative", 0.85),
    ("FP-BOND-001", "FP-BOND-005", "alternative", 0.90),
    ("FP-BOND-002", "FP-BOND-001", "alternative", 0.85),
    ("FP-BOND-002", "FP-BOND-005", "alternative", 0.80),
    ("FP-BOND-006", "FP-BOND-002", "alternative", 0.90),  # backordered -> available
    ("FP-BOND-006", "FP-BOND-005", "alternative", 0.85),
    # Cardstock alternatives
    ("FP-CARD-001", "FP-CARD-004", "alternative", 0.80),
    ("FP-CARD-002", "FP-CARD-003", "upsell", 0.70),
    ("FP-CARD-004", "FP-CARD-003", "upsell", 0.65),
    # Coated paper alternatives
    ("FP-COAT-001", "FP-COAT-002", "alternative", 0.75),
    ("FP-COAT-002", "FP-COAT-001", "upsell", 0.70),
    # Box alternatives & complements
    ("PK-BOX-001", "PK-BOX-002", "alternative", 0.70),
    ("PK-BOX-001", "PK-TAPE-001", "complementary", 0.90),
    ("PK-BOX-001", "PK-PROT-001", "complementary", 0.85),
    ("PK-BOX-002", "PK-BOX-003", "upsell", 0.75),
    ("PK-BOX-002", "PK-TAPE-001", "complementary", 0.90),
    ("PK-BOX-002", "PK-FILM-002", "complementary", 0.80),
    ("PK-BOX-003", "PK-PROT-002", "complementary", 0.85),
    ("PK-BOX-005", "PK-BOX-004", "alternative", 0.70),
    ("PK-BOX-006", "PK-BOX-003", "alternative", 0.90),  # backordered -> available
    # Mailer complements
    ("PK-MAIL-001", "PK-PROT-001", "complementary", 0.60),
    ("PK-MAIL-002", "PK-TAPE-001", "complementary", 0.70),
    # Stretch film accessories
    ("PK-FILM-001", "PK-FILM-002", "alternative", 0.65),  # machine vs hand
    ("PK-FILM-002", "PK-FILM-001", "upsell", 0.65),
    # Tape alternatives
    ("PK-TAPE-001", "PK-TAPE-002", "alternative", 0.80),
    ("PK-TAPE-001", "IN-ADH-003", "alternative", 0.40),
    # Copy paper alternatives
    ("OF-CPY-001", "OF-CPY-002", "alternative", 0.90),
    ("OF-CPY-001", "OF-CPY-005", "alternative", 0.85),
    ("OF-CPY-002", "OF-CPY-001", "alternative", 0.90),
    ("OF-CPY-001", "OF-CPY-003", "upsell", 0.70),
    ("OF-CPY-004", "FP-UNCO-001", "alternative", 0.60),
    # Toner accessories
    ("OF-TNR-001", "OF-CPY-001", "complementary", 0.80),
    ("OF-TNR-002", "OF-CPY-001", "complementary", 0.75),
    ("OF-TNR-004", "OF-TNR-003", "alternative", 0.50),  # discontinued -> available
    # Binder accessories
    ("OF-BND-001", "OF-LBL-001", "complementary", 0.60),
    ("OF-BND-001", "OF-BND-002", "upsell", 0.70),
    # Cup & lid combos
    ("FD-CUP-001", "FD-CUP-003", "complementary", 0.95),
    ("FD-CUP-002", "FD-CUP-003", "complementary", 0.80),
    ("FD-CUP-001", "FD-CUP-002", "alternative", 0.50),
    # Napkin alternatives
    ("FD-NAP-001", "FD-NAP-002", "alternative", 0.70),
    # Utensil combos
    ("FD-UTN-001", "FD-UTN-002", "upsell", 0.80),
    # Food container complements
    ("FD-CNT-001", "FD-UTN-002", "complementary", 0.75),
    ("FD-CNT-002", "FD-UTN-001", "complementary", 0.70),
    # Cleaning supplies combo
    ("FS-CLN-001", "FS-TOW-001", "complementary", 0.80),
    ("FS-CLN-002", "FS-SAF-002", "complementary", 0.85),
    # Safety gear combo
    ("FS-SAF-001", "FS-SAF-002", "complementary", 0.80),
    ("FS-SAF-001", "FS-SAF-003", "complementary", 0.75),
    # Wide format complements
    ("WF-VIN-001", "WF-VIN-002", "alternative", 0.85),
    ("WF-CAN-001", "WF-CAN-002", "alternative", 0.80),
    ("WF-CAN-002", "WF-CAN-001", "upsell", 0.75),
    # Envelope alternatives
    ("ENV-STD-001", "ENV-STD-002", "alternative", 0.80),
    ("ENV-STD-001", "ENV-STD-003", "upsell", 0.70),
    ("ENV-CAT-001", "ENV-CAT-002", "alternative", 0.85),
    # Industrial adhesive alternatives
    ("IN-ADH-001", "IN-ADH-002", "alternative", 0.50),
    ("IN-ADH-002", "IN-ADH-003", "alternative", 0.55),
    # Abrasive alternatives
    ("IN-ABR-001", "IN-ABR-002", "alternative", 0.40),
    # Fastener combos
    ("IN-FST-001", "IN-FST-003", "complementary", 0.85),
]


async def ensure_database_seeded():
    """Create tables and seed data if empty. Called on agent startup."""
    import asyncpg

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.warning("DATABASE_URL not set — skipping database seed")
        return

    conn = await asyncpg.connect(database_url)
    try:
        # Create tables
        await conn.execute(CREATE_TABLES_SQL)
        logger.info("Supplier tables created/verified.")

        # Check if already seeded
        count = await conn.fetchval("SELECT COUNT(*) FROM supplier_products")
        if count > 0:
            logger.info(f"Database already has {count} products — skipping seed.")
            return

        logger.info("Seeding supplier database with synthetic data...")

        # Insert categories
        for cat_id, name, parent_id, desc in CATEGORIES:
            await conn.execute(
                "INSERT INTO supplier_categories (id, name, parent_category_id, description) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                cat_id, name, parent_id, desc
            )
        # Reset sequence
        await conn.execute("SELECT setval('supplier_categories_id_seq', (SELECT MAX(id) FROM supplier_categories))")

        # Insert manufacturers
        for mfr_id, name, website, country, lead_min, lead_max in MANUFACTURERS:
            await conn.execute(
                "INSERT INTO supplier_manufacturers (id, name, website, country, lead_time_days_min, lead_time_days_max) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
                mfr_id, name, website, country, lead_min, lead_max
            )
        await conn.execute("SELECT setval('supplier_manufacturers_id_seq', (SELECT MAX(id) FROM supplier_manufacturers))")

        # Insert products
        sku_to_id = {}
        for p in PRODUCTS:
            sku, name, desc, cat_id, mfr_id, price, uom, weight, dims, status, qty, lead, moq, tags = p
            product_id = await conn.fetchval(
                """INSERT INTO supplier_products
                   (sku, name, description, category_id, manufacturer_id, unit_price, unit_of_measure,
                    weight_lbs, dimensions, stock_status, stock_quantity, lead_time_days, minimum_order_quantity, tags)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                   RETURNING id""",
                sku, name, desc, cat_id, mfr_id, price, uom, weight, dims, status, qty, lead, moq, tags
            )
            sku_to_id[sku] = product_id

        # Insert price tiers
        for sku, min_q, max_q, price, disc in PRICE_TIERS:
            if sku in sku_to_id:
                await conn.execute(
                    "INSERT INTO supplier_price_tiers (product_id, min_quantity, max_quantity, unit_price, discount_percent) VALUES ($1,$2,$3,$4,$5)",
                    sku_to_id[sku], min_q, max_q, price, disc
                )

        # Insert product relations
        for sku1, sku2, rel_type, score in PRODUCT_RELATIONS:
            if sku1 in sku_to_id and sku2 in sku_to_id:
                await conn.execute(
                    "INSERT INTO supplier_product_relations (product_id, related_product_id, relation_type, relevance_score) VALUES ($1,$2,$3,$4)",
                    sku_to_id[sku1], sku_to_id[sku2], rel_type, score
                )

        total_products = len(PRODUCTS)
        total_tiers = len(PRICE_TIERS)
        total_relations = len(PRODUCT_RELATIONS)
        logger.info(f"Seed complete: {total_products} products, {total_tiers} price tiers, {total_relations} relations.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(ensure_database_seeded())
