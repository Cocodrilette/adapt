# **Adapt Specification: Core Engine**

> **Status:** This document is maintained as an implementation specification.
> The running code on `main` wins if they differ. This is not a roadmap or the
> authoritative user documentation. See the
> [documentation contract](../README.md) and [user manual](../manual/index.md).

## **1. File Discovery Engine**

### **Purpose**

Scan the document root and identify all resources to expose.

### **Responsibilities**

* Recursively walk the root directory
* Identify supported file types
* Associate companion files (schema, HTML UI, write overrides)
* Detect Python handler files
* Produce a list of resources to load via plugins

### **Supported File Types**

| Extension  | Handler               |
| ---------- | --------------------- |
| `.csv`     | CSV Plugin            |
| `.xlsx`    | Excel Plugin          |
| `.html`    | HTML Plugin           |
| `.md`      | Markdown Plugin       |
| `.parquet` | Parquet Plugin        |
| `.py`      | Python Handler Plugin |
| `.txt`     | Generic File Plugin   |
| `.pdf`     | Generic File Plugin   |
| `.json`    | Generic File Plugin   |
| `.xml`     | Generic File Plugin   |
| `.svg`     | Generic File Plugin   |
| `.png`     | Generic File Plugin   |
| `.jpg`     | Generic File Plugin   |
| `.jpeg`    | Generic File Plugin   |
| `.gif`     | Generic File Plugin   |
| `.webp`    | Generic File Plugin   |
| `.mp4`     | Media Plugin          |
| `.mp3`     | Media Plugin          |
| `.avi`     | Media Plugin          |
| `.mkv`     | Media Plugin          |
| `.webm`    | Media Plugin          |
| `.ogg`     | Media Plugin          |
| `.wav`     | Media Plugin          |

The default registry maps `.xls` to the Excel plugin. However, the plugin only
accepts `.xlsx`, so `.xls` is not readable. The discovery engine ignores
unregistered extensions.

## **2. Dataset Engine**

Handles structured datasets (CSV, Excel sheets, Parquet-like).

### **Responsibilities**

* Schema inference
* Row-level CRUD
* Inline editing via PATCH
* Duplicate row ID management
* Write-through with locking
* Companion file generation

### **Supported Types**

string, integer, number, boolean

These inferred labels affect response serialization and default UI columns.
They do not validate mutation payloads.

### **Excel Behavior**

Each sheet becomes a resource via the "sub_namespace" mechanism:

* `/api/file/<sheet>` — CRUD API for each sheet
* `/ui/file/<sheet>` — HTML UI for each sheet
* `/schema/file/<sheet>` — Schema for each sheet

Each sheet uses these companion filenames:

* `.adapt/file.<sheet>.schema.json`
* `.adapt/file.<sheet>.index.html`
* `.adapt/file.<sheet>.options.json`

Adapt generates the schema and UI files. The options file is hand-maintained.

---

## **3. Schema Engine**

### **Responsibilities**

* Infer schema from CSV/XLSX
* Merge schema overrides
* Generate default schema files
* Supply serialization hints and UI column metadata

Neither inferred nor hand-maintained schemas are write validators.

---

## **4. Safe Writes (Locking + Atomic Write System)**

### **Current Behavior**

* One writer at a time (enforced via database unique constraint)
* One lock record per resource
* Built-in dataset writes use a temporary file and atomic target replacement
  where the platform supports it
* Locks recorded and visible in Admin UI
* Lock expiration with TTL (5 minutes default)
* Retry with timeout (30 seconds) and exponential backoff (0.1s initial, doubling, 1.0s max)

These behaviors reduce race and partial-write risk; they do not eliminate all
races or make a writer uninterruptible. When retries are exhausted, the
current timeout is not translated reliably into an HTTP `409` and may surface
as a server error.

### **Implementation Details**

**Optimistic Locking Pattern:**
1. Try to insert lock record directly
2. Database enforces uniqueness via constraint
3. On IntegrityError, check if existing lock is expired
4. Delete stale lock and retry
5. Retry a held lock with exponential backoff until the context timeout

**Automatic Recovery:**
* Server startup cleans locks older than 5 minutes
* Ensures recovery from crashes without manual intervention
* Background monitoring via Admin UI

---

## **5. Cache Engine**

### **Features**

* Plugin-specific caching of parsed dataset rows, schemas, rendered/read HTML
  and Markdown, and extracted media metadata
* Resource-scoped invalidation by plugins after supported writes
* Cache visibility and clearing via Admin UI

Generic file bodies and streamed media bodies are not cached. There is no
automatic cache wrapper for every GET response.

---

## **6. Companion File Specification**

Adapt treats your filesystem as a structured backend environment. Companion files (schemas, UIs, overrides) are stored in a hidden `.adapt` directory to keep the docroot clean.

### **Generation**

During startup, Adapt generates missing dataset schema and UI files in the
`.adapt/` directory. Adapt reads options files but does not generate them.

### **Generated Files**

| Type                                       | Default Content                                    | Description |
| ------------------------------------------ | -------------------------------------------------- | ----------- |
| Schema (`.adapt/*.schema.json`)            | JSON schema inferred from dataset                  | JSON schema for dataset |
| HTML UI (`.adapt/*.index.html`)            | Jinja2 template with pre-computed schema           | Customizable HTML UI template |
| Sheet UI (`.adapt/*.<sheet>.index.html`)   | Default sheet-level UI                             | Customizable HTML UI template |

The media plugin is an exception to the UI content type. It writes JSON
metadata to its assigned `ui_path` instead of an HTML template.

### **Example generated schema**

```json
{
  "type": "object",
  "primary_key": "_row_id",
* Handles structured datasets (CSV, Excel sheets, Parquet). Parquet support is now robust and consistent with other dataset plugins, including atomic writes and schema inference.
    "name": {"type": "string"},
    "age": {"type": "integer"}
  }
}
```
