import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

# Standard 7 Architectural Layers for Android & Web Enterprise Projects
FEATURE_LAYERS = [
    {
        "folder": "01_DOMAIN_AND_RULES",
        "title": "Domain Logic, Rules & State Machines",
        "layer_code": "LAYER_1_DOMAIN",
        "files": [
            {
                "filename": "01_domain_models.md",
                "title": "Domain Aggregate Roots, Entities & Value Objects",
                "invariants": [],
                "template": """# 🏛️ Domain Models & Aggregate Roots
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `01_DOMAIN_AND_RULES`

---

## 🎯 1. Core Aggregate Roots & Entities
- Define pure domain classes without framework dependencies.
- Ensure immutable data models with explicit value objects.

### Entity Definitions:
```kotlin
// Define domain models here
```
"""
            },
            {
                "filename": "02_fsm_state_machine.md",
                "title": "Finite State Machine & State Transition Matrix",
                "invariants": [],
                "template": """# 🔄 Finite State Machine (FSM)
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `01_DOMAIN_AND_RULES`

---

## 🎯 1. States & Valid Transitions
List all valid states and strictly forbid illegal direct jumps.

| From State | Trigger Event | To State | Side Effects |
| :--- | :--- | :--- | :--- |
| `INITIAL` | `START` | `IN_PROGRESS` | Create audit log |

---

## 🚫 2. Illegal Transitions (Must Throw Exception)
- Transitions not in the matrix above must fail immediately.
"""
            },
            {
                "filename": "03_financial_math.md",
                "title": "Financial Math & Integer Paise Invariants",
                "invariants": [
                    {
                        "id": "INV-FIN-001",
                        "layer": "LAYER_1_DOMAIN",
                        "title": "Law ACC-001 Zero Float Financial Math",
                        "rule_type": "FORBIDDEN_TOKENS",
                        "file_patterns": ["**/domain/**", "**/billing/**", "**/repair/**", "**/ledger/**"],
                        "params": {"forbidden_tokens": ["Float", "Double", "0.18f", "BigDecimal.toFloat"]},
                        "enforcement": "BLOCK_BUILD",
                    }
                ],
                "template": """# 💰 Financial Math & Invariants
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `01_DOMAIN_AND_RULES`

---

## 🎯 1. Strict Law ACC-001 Integer Currency
- All monetary amounts MUST be represented in 64-bit integer paise (`Long` in Kotlin, `number` / `bigint` in TypeScript).
- Floating-point representations (`Float`, `Double`) are strictly forbidden.

<!-- UNIGOV_INVARIANT_START -->
{invariants_block}
<!-- UNIGOV_INVARIANT_END -->

---

## 🧮 2. Tax & Margin Formulas
- Rounding rules: half-up integer rounding: `(amountPaise * taxRate + 50) / 100`.
"""
            }
        ]
    },
    {
        "folder": "02_DATA_AND_STORAGE",
        "title": "Database Schema, Sync & Storage Contracts",
        "layer_code": "LAYER_2_DATA",
        "files": [
            {
                "filename": "01_room_sqlite_schema.md",
                "title": "Room SQLite WAL Tables & Foreign Keys",
                "invariants": [],
                "template": """# 🗄️ Room SQLite Schema
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `02_DATA_AND_STORAGE`

---

## 🎯 1. Table Definitions & Indexes
- Foreign key cascade policies and compound query indexes.
"""
            },
            {
                "filename": "02_firestore_contract.md",
                "title": "Cloud Firestore JSON Documents & Security Rules",
                "invariants": [],
                "template": """# ☁️ Firestore Document Contract
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `02_DATA_AND_STORAGE`

---

## 🎯 1. Document Schema & Collection Path
- Collection: `stores/{{storeId}}/{feature_slug}`
"""
            },
            {
                "filename": "03_migrations_and_indexes.md",
                "title": "Database Migrations & Idempotency Invariants",
                "invariants": [
                    {
                        "id": "INV-SYNC-001",
                        "layer": "LAYER_2_DATA",
                        "title": "Mandatory Client Idempotency Key",
                        "rule_type": "REQUIRED_COLUMNS",
                        "file_patterns": ["**/data/local/entity/**", "**/models/**"],
                        "params": {"required_columns": ["idempotency_key", "sync_status"]},
                        "enforcement": "BLOCK_BUILD",
                    }
                ],
                "template": """# 🔄 Migrations & Idempotency
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `02_DATA_AND_STORAGE`

---

## 🎯 1. Idempotency Key & Offline Sync Safety
<!-- UNIGOV_INVARIANT_START -->
{invariants_block}
<!-- UNIGOV_INVARIANT_END -->
"""
            }
        ]
    },
    {
        "folder": "03_ANDROID_COMPOSE",
        "title": "Android Jetpack Compose Surfaces",
        "layer_code": "LAYER_3_SURFACES",
        "files": [
            {
                "filename": "01_screens_and_navigation.md",
                "title": "Compose Navigation Graph & Screen Architecture",
                "invariants": [],
                "template": """# 📱 Android Compose Screens & Navigation
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `03_ANDROID_COMPOSE`

---

## 🎯 1. Screen Hierarchy & Navigation Routes
- Composable entry points and ViewModel StateFlow architecture.
"""
            },
            {
                "filename": "02_5_mandatory_ui_states.md",
                "title": "Mandatory 5 UI States Enforcement",
                "invariants": [
                    {
                        "id": "INV-UI-001",
                        "layer": "LAYER_3_SURFACES",
                        "title": "Mandatory 5-State Screen Handling",
                        "rule_type": "MANDATORY_UI_STATES",
                        "file_patterns": ["**/ui/**/*.kt", "**/components/**/*.kt"],
                        "params": {"required_states": ["Loading", "Empty", "Error", "Offline", "Populated"]},
                        "enforcement": "WARN",
                    }
                ],
                "template": """# 🎨 5 Mandatory Screen States
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `03_ANDROID_COMPOSE`

---

## 🎯 1. The 5 Compulsory States
Every screen MUST handle:
1. **Skeleton Loading State**
2. **Empty State**
3. **Error State with Retry Action**
4. **Offline Mode Banner**
5. **Populated Data State**

<!-- UNIGOV_INVARIANT_START -->
{invariants_block}
<!-- UNIGOV_INVARIANT_END -->
"""
            },
            {
                "filename": "03_components_and_canvas.md",
                "title": "Custom Canvas, Haptics & Gestures",
                "invariants": [],
                "template": """# 🖌️ Custom Components & Canvas
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `03_ANDROID_COMPOSE`

---

## 🎯 1. Custom Drawing & Interactive Canvas
- Tactile widgets, gesture handling, Canvas rendering.
"""
            }
        ]
    },
    {
        "folder": "04_WEB_PORTAL",
        "title": "Web Portal Next.js Workstations",
        "layer_code": "LAYER_3_SURFACES",
        "files": [
            {
                "filename": "01_page_routes_and_drawers.md",
                "title": "Next.js 15 App Router Workstations",
                "invariants": [],
                "template": """# 🌐 Web Portal Routes & Workstations
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `04_WEB_PORTAL`

---

## 🎯 1. Route Hierarchy
- Route: `web/src/app/{feature_slug}/page.tsx`
- Modals, drawers, and responsive layout.
"""
            },
            {
                "filename": "02_kanban_desk_and_sla.md",
                "title": "Kanban Desk, Real-Time Subscriptions & SLA Engine",
                "invariants": [],
                "template": """# ⏱️ Kanban Desk & SLA Engine
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `04_WEB_PORTAL`

---

## 🎯 1. SLA Countdown & Real-Time Desk
- Real-time Firestore subscriptions and SLA overdue alerts.
"""
            },
            {
                "filename": "03_print_sheets.md",
                "title": "Printable Sheets, Receipts & Slips",
                "invariants": [],
                "template": """# 🖨️ Printable Slips & Sheets
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `04_WEB_PORTAL`

---

## 🎯 1. Print Formats
- Customer Copy & Workshop/Store Copy (A4 & 80mm thermal layouts).
"""
            }
        ]
    },
    {
        "folder": "05_HARDWARE_PERIPHERALS",
        "title": "Hardware Peripherals, Printers & Drivers",
        "layer_code": "LAYER_3_SURFACES",
        "files": [
            {
                "filename": "01_printers_and_scanners.md",
                "title": "ESC/POS Thermal Printers & CameraX Barcode Scanners",
                "invariants": [],
                "template": """# 🖨️ Hardware Peripherals & Drivers
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `05_HARDWARE_PERIPHERALS`

---

## 🎯 1. ESC/POS Thermal Printing Protocols
- 58mm & 80mm ESC/POS byte generator (code page 437/dynamic QR).
- CameraX barcode & 15-digit Luhn IMEI scanner specs.
"""
            }
        ]
    },
    {
        "folder": "06_SECURITY_AND_TESTS",
        "title": "Security, RBAC & Automated Test Pyramid",
        "layer_code": "LAYER_4_SECURITY",
        "files": [
            {
                "filename": "01_rbac_and_permissions.md",
                "title": "Role-Based Access Control & Keystore Encryption",
                "invariants": [
                    {
                        "id": "INV-SEC-001",
                        "layer": "LAYER_4_SECURITY",
                        "title": "Zero Hardcoded Secret Tokens",
                        "rule_type": "FORBIDDEN_TOKENS",
                        "file_patterns": ["**/*.kt", "**/*.ts", "**/*.py"],
                        "params": {"forbidden_patterns": ["AIza[0-9A-Za-z-_]{35}", "ghp_[0-9A-Za-z]{36}"]},
                        "enforcement": "BLOCK_BUILD",
                    }
                ],
                "template": """# 🔒 Security & RBAC
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `06_SECURITY_AND_TESTS`

---

## 🎯 1. Role-Based Permissions
- Roles: `OWNER`, `CASHIER`, `TECHNICIAN`.

<!-- UNIGOV_INVARIANT_START -->
{invariants_block}
<!-- UNIGOV_INVARIANT_END -->
"""
            },
            {
                "filename": "02_unit_and_integration_tests.md",
                "title": "Unit Tests & Regression Test Gates",
                "invariants": [],
                "template": """# 🧪 Test Strategy & Verification Gates
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `06_SECURITY_AND_TESTS`

---

## 🎯 1. Test Execution Commands
- Unit tests: `./gradlew testDebugUnitTest`
- Web build: `npm run build`
"""
            }
        ]
    },
    {
        "folder": "07_REPORTS_AND_PROFIT",
        "title": "P&L Reports, Stock Outward & Daily Closing",
        "layer_code": "LAYER_5_INTELLIGENCE",
        "files": [
            {
                "filename": "01_stock_deduction_and_pnl.md",
                "title": "Spare Parts Stock Outward & Net Profit Sync",
                "invariants": [],
                "template": """# 📊 Stock Outward & P&L Reports Sync
**Feature:** {feature_title} (`{feature_slug}`)  
**Layer:** `07_REPORTS_AND_PROFIT`

---

## 🎯 1. Stock Outward Triggers
- Automatic inventory depletion when items/parts are consumed.

---

## 💰 2. Net Profit Calculation
- Formula: `Gross Revenue - Purchase Cost - Technician Commission = Dukan Net Profit`.
- Sync to Daily Closing & Day Summary.
"""
            }
        ]
    }
]


def sanitize_feature_slug(name: str) -> str:
    """Converts a feature name into a clean alphanumeric slug with underscores."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower())
    return re.sub(r"_+", "_", slug).strip("_")


def scaffold_feature_suite(
    feature_slug: str,
    feature_title: str,
    base_dir: Path,
    overwrite: bool = False
) -> Dict[str, Any]:
    """
    Creates the 7-Layer Hierarchical Document Structure for a specific feature:
    base_dir/
      01_DOMAIN_AND_RULES/<feature_slug>/*.md
      02_DATA_AND_STORAGE/<feature_slug>/*.md
      03_ANDROID_COMPOSE/<feature_slug>/*.md
      04_WEB_PORTAL/<feature_slug>/*.md
      05_HARDWARE_PERIPHERALS/<feature_slug>/*.md
      06_SECURITY_AND_TESTS/<feature_slug>/*.md
      07_REPORTS_AND_PROFIT/<feature_slug>/*.md
    """
    clean_slug = sanitize_feature_slug(feature_slug)
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    created_files: List[Path] = []
    skipped_files: List[Path] = []

    for layer in FEATURE_LAYERS:
        layer_folder = base_dir / layer["folder"] / clean_slug
        layer_folder.mkdir(parents=True, exist_ok=True)

        for doc in layer["files"]:
            file_path = layer_folder / doc["filename"]
            if file_path.exists() and not overwrite:
                skipped_files.append(file_path)
                continue

            # Format invariants block if any
            invariants_block = ""
            if doc.get("invariants"):
                invariants_block = json.dumps(doc["invariants"], indent=2)

            content = doc["template"].format(
                feature_title=feature_title,
                feature_slug=clean_slug,
                invariants_block=invariants_block
            )

            file_path.write_text(content.strip() + "\n", encoding="utf-8")
            created_files.append(file_path)

    return {
        "feature_slug": clean_slug,
        "feature_title": feature_title,
        "base_dir": str(base_dir),
        "total_created": len(created_files),
        "total_skipped": len(skipped_files),
        "created_files": [str(p) for p in created_files],
        "skipped_files": [str(p) for p in skipped_files],
    }


def list_project_features(base_dir: Path) -> List[Dict[str, Any]]:
    """
    Scans the base directory across all 7 dimension folders and returns
    a summary of all features found and their document coverage.
    """
    base_dir = Path(base_dir)
    if not base_dir.exists():
        return []

    # Map: feature_slug -> {layer_folder: count_of_files}
    features_map: Dict[str, Dict[str, int]] = {}

    for layer in FEATURE_LAYERS:
        layer_dir = base_dir / layer["folder"]
        if not layer_dir.exists():
            continue

        for feature_folder in layer_dir.iterdir():
            if feature_folder.is_dir() and not feature_folder.name.startswith("."):
                slug = feature_folder.name
                if slug not in features_map:
                    features_map[slug] = {l["folder"]: 0 for l in FEATURE_LAYERS}
                
                md_count = len(list(feature_folder.glob("*.md")))
                features_map[slug][layer["folder"]] = md_count

    results = []
    for slug, layers in sorted(features_map.items()):
        total_docs = sum(layers.values())
        results.append({
            "feature_slug": slug,
            "total_docs": total_docs,
            "layers": layers,
        })

    return results
