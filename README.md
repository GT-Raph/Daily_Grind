# The Daily Grind

A Django site with server-rendered templates, SQLite and progressively enhanced JavaScript. React, TypeScript and Vite are no longer required to run or build the site. The current cup-and-beans design, images and content are preserved.

## Run locally (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py import_shop_menu --apply
.venv\Scripts\python.exe manage.py runserver
```

Open http://127.0.0.1:8000/. No virtual-environment activation or npm build is needed.

On macOS/Linux, use `.venv/bin/python` in place of `.venv\Scripts\python.exe`.

## Edit the site

- `website/templates/website/`: base, page and reusable section templates.
- `website/static/website/styles.css`: existing visual system and responsive layouts.
- `website/static/website/site.js`: scrolling story, navigation, menu filters and reviews.
- `website/data/content.json`: shop details, review excerpts and hours; its original menu is now migration reference only. Live products, descriptions, categories, prices and availability are stored in the database.
- `website/data/menu_2026_10_05.json`: the owner's PDF menu, transcribed with source URL and page references; imported explicitly with `import_shop_menu`.
- `public/images/`: existing image assets, served through Django's static files.
- `website/models.py`, `forms.py`, `views.py`: signup storage, validation and request handling.
- `website/order_views.py`, `cart.py`, `notifications.py`: pickup checkout, basket and notification delivery.
- `staff_portal/`: separate staff sign-in, order dashboard, templates and live queue script.
- `website/static/website/orders.css` and `orders.js`: ordering styles, basket feedback and live status updates.
- `config/settings.py`: environment configuration; time zone is Africa/Accra.

Lenis 1.3.26 is vendored locally for the existing smooth scrolling, with its MIT license in `website/static/website/vendor/`. Big Shoulders and Figtree are self-hosted in `website/static/website/fonts/` with their font licenses. There is no JavaScript compilation step. Reduced motion shows the story as normal sections and stops decorative animation. With JavaScript disabled, content, contact links and signup still work.

## Subscribers and administration

The signup form saves normalized, unique email addresses in the local database. It validates input, uses CSRF protection and redirects after a successful POST. It does not send email or connect to a mailing provider.

```powershell
.venv\Scripts\python.exe manage.py createsuperuser
```

Then sign in at `/admin/` to view or remove subscribers. No default admin password is created.

## Pickup orders

Customers add menu items to a session basket, update quantities, and leave a name, phone number and optional note at `/order/checkout/`. Orders are saved atomically with price snapshots and one email notification job. Menu, basket and checkout prices always come from administrator-managed `MenuPrice` records and applicable discounts; client-submitted prices are ignored. Payment is due at the shop. There is no online payment or delivery checkout.

The customer receives a private, session-bound receipt with a reference and live status. Keep that page open to see the shop accept the order and mark it ready. Repeated checkout submissions return the existing order. Clearing browser cookies removes access to old receipts; customers can call with their reference.

Staff open **`/staff/`**, which has its own sign-in at `/staff/login/`, navigation and sign-out. It uses existing Django staff accounts and has no customer menu or basket navigation. The screen refreshes every 10 seconds, shows contact details and notes, and supports accept → ready → paid and collected, or cancellation. Recent history contains the last 50 completed/cancelled orders; the Administration link opens the full archive at `/admin/`. Old `/shop/orders/` bookmarks redirect to the staff section.

For non-superusers, grant staff status plus `website | order | Can view order`; add `Can change order` to allow updates. View-only staff see the queue without action buttons. Customers cannot sign in to or access the staff queue, including its live updates and status endpoints. Staff share Django's authentication session with `/admin/`; signing out ends that session. The customer site remains at `/`, and checkout and email notifications work independently of whether the staff screen is open.

Online ordering is enabled in local debug mode. Before enabling it on a public site, import the supplied menu, set up email below and keep the worker running. Set `ORDERING_ENABLED=1` to enable production ordering, or `0` to show a call-to-order fallback.

## Supplied PDF menu

The menu was checked against all five pages of the owner's **TDG MENU FINAL .pdf** on 5 October 2026: [source menu](https://drive.google.com/file/d/1pZsfDeBi4RSDt9mDIJ4Ks8eMM4lK7_KR/view). It contains 68 entries across hot/cold coffees, non-coffee blends, juices, smoothies, panini, breakfast, croissants, combos and saj wraps. The public contact number is **020 622 9966** and opening hours are **7am–10pm daily**, as printed in the PDF. Email notification settings are unchanged.

Menu imagery is illustrative, not photography of the shop's actual servings. Product images live in `public/images/menu/` and the source menu records their local paths. New artwork was generated with the built-in image tool as transparent product cutouts, then packaged as WebP files up to 640 pixels for menu cards and basket thumbnails. Exact generation prompts are kept in `website/data/menu_image_prompts/`, with provenance sidecars beside the WebP files. Existing product photos are retained.

For an existing database, `manage.py attach_menu_images` previews missing photo assignments; add `--apply` to attach them without reimporting prices or changing other menu fields. Products with an existing local image or administrator-provided photo URL are left alone. New installations receive the images through the normal source-menu import below. An administrator can replace a product illustration using its Photo URL field.

`manage.py import_shop_menu` previews the update; `--apply` saves a menu-only backup under `.migration-backups/`, updates matching records, adds missing items and hides records absent from the PDF. It preserves order snapshots, customers and discount rules. It runs only when explicitly invoked, so subsequent admin edits are not overwritten on restart or migration. Reapplying deliberately restores the supplied menu; do not rerun it to preserve later shop edits. Source metadata and page numbers live in `website/data/menu_2026_10_05.json`.

Soul Shot displays **GH₵30 / 45** and Morning Ritual **GH₵120–140**, with call-to-order buttons because the PDF does not map those prices to choices. This handling was confirmed by the owner. Custom croissants and add-ons also require a call; no base price or unlisted option surcharge is invented. Fixed-price combos can be ordered online; checkout requires the drink/food choices in the order notes, which accompany the saved order and email. Phone-only prices are quoted as printed, without automatically applying online discounts.

## Administrator-only menu and prices

Sign in as an administrator at **`/admin/website/menuprice/`** (Administration → Website → Menu products). Choose **Add menu product**, enter a name, choose **Coffee**, **Tea**, **Juices & smoothies** or **Food**, enter its price in Ghana cedis, and save. Description and an HTTPS photo URL are optional. Without a photo, new products use the existing bean mark. Lower display-order numbers appear first. Existing matching photos are preserved.

Use **Call to order** for items requiring a shop quote; **Display price** accepts the printed range or “Ask for price”. Online items must have a numeric price and cannot use a display-price override. Use **Required order choices** to prompt combo selections at checkout. Only administrators can edit these fields.

Edit a product to change its name, category, description or price. Uncheck **On the menu** to hide it temporarily, or use the list actions to remove/restore selected products. **Delete** permanently removes the menu record and any discount specific to it. Past orders retain their names, quantities and prices. Hidden/deleted items cannot be newly ordered, and customers must review a changed basket before submitting it. Discounts apply to newly added products too.

Administrator means an active Django superuser with staff access. Regular staff cannot create, edit, hide, restore or delete products, even if they are accidentally given menu-product model permissions. Grant ordinary staff only the order permissions described above, never superuser status.

Changes take effect on the next menu, basket or checkout request without restarting the server. A checkout opened before a price change requires the customer to review the new total before placing the order. Submitted orders keep their original unit prices and totals; neither staff nor administrators can edit these snapshots through the admin. Django's History page records who changed a menu price.

Migration `0003_menuprice` creates the existing 16 menu prices. Migration `0005_menu_products_and_customers` adds their categories, descriptions and photos without resetting edited prices or discounts. The former Tea & other group is assigned to Tea, including its non-coffee drinks; administrators can edit categories. Menu edits no longer require source changes or migrations. Price forms accept positive amounts with up to two decimal places. The internal `MenuPrice` model and URL are retained for compatibility.

## Owner customer history

Open **`/admin/website/customer/`** (Administration → Website → Customers). This owner-only, read-only report ranks customers by collected-order count, then total collected spending. It shows phone numbers, collected-order counts, spending, the last order date and an order-history link. Order dates reflect when orders were placed, including those still in progress. Open a customer for first/last order dates, or select **Repeat customers (2+ collected orders)** in the activity filter. Search by name or phone; both local Ghanaian and international formats work.

Checkout links orders by the normalized phone number and uses the latest name supplied for that number. Local `024…` and matching `+23324…` numbers form one customer. Shared numbers share a history; these are checkout contact details, not verified customer accounts. The migration backfills existing orders. All aggregates are calculated from current order records, so pending/cancelled orders do not inflate spending, duplicate checkout retries do not add visits, and status changes are reflected immediately. Spending uses the discounted amount actually saved on each collected order. No points, rewards or marketing messages are added.

## Administrator-only discounts

Open **`/admin/website/discount/`** (Administration → Website → Discounts), choose **Add discount**, then select **All products** or **One product**. For one product, select its name; for all products, leave Product empty. Enter a percentage from 0 to 100 (up to two decimal places) and save. Regular staff cannot view, add, edit or delete these rules, even with discount model permissions.

There can be one all-products discount and one override per product. A product-specific percentage **replaces** the all-products percentage; discounts never stack. Set a product override to 0% to exclude it from a storewide offer. Delete the override to make it use the all-products discount again; delete the all-products rule to end that offer. The form explains these rules, and History records changes.

The menu, basket and checkout show the resulting price automatically. Discounts apply to each unit's base price, rounded half up to two decimal places before multiplying by quantity. A 100% discount makes that product free. Base prices and submitted orders are preserved. Changing or removing a discount during checkout requires the customer to review any changed total. No discounts are enabled by the migration.

## Email order notifications

Order notifications are sent by email only, to **mailsmartshots@gmail.com**. Override the recipient with `SHOP_ORDER_EMAIL` if needed. No provider credentials are built into the source.

The project-root **`.env` file is loaded automatically** by Django and the notification worker. It contains the recipient and Gmail SMTP settings. `EMAIL_HOST_PASSWORD` must be a Google App Password without display spaces; enclose the value in quotes to preserve literal characters such as `#`. Restart both processes after editing. Existing process environment variables take precedence over `.env`. The local loader supports single-line `KEY=value` entries, optional single/double quotes and comments; values are literal, with no shell execution, escape decoding or variable expansion. `.env` is already ignored by git. Use your hosting provider's secret settings in production.

| Variable | Purpose |
| --- | --- |
| `SHOP_ORDER_EMAIL` | Shop inbox that receives new orders |
| `DEFAULT_FROM_EMAIL` | Sender verified with your email provider |
| `EMAIL_HOST`, `EMAIL_PORT` | SMTP server and port (default 587) |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP credentials from the provider |
| `EMAIL_USE_TLS`, `EMAIL_USE_SSL` | Use `1` or `0`; default TLS=1, SSL=0. For port 465, set TLS=0 and SSL=1. |

Each email includes the order reference, customer name and phone number, ordered items, pickup total and customer note. See [Django email settings](https://docs.djangoproject.com/en/5.2/topics/email/).

After setting the environment variables and restarting Django, run a second terminal with the same environment:

```powershell
.venv\Scripts\python.exe manage.py process_order_notifications --watch
```

The worker checks the durable queue every five seconds. In production, run this command as a supervised service alongside the web process, with access to the same database and automatic restarts. For a one-time run, omit `--watch`. An open staff browser is not a substitute for the worker.

Email failures retry up to five attempts with backoff. Missing configuration waits without consuming attempts. Failed emails remain visible on the staff screen; after correcting configuration, use the order admin action **Retry failed / unconfigured order alerts**. An email failure never deletes the order. Claims have a two-minute lease so interrupted jobs can be recovered. Historical non-email notification records are preserved, but are excluded from sending, retries and the staff notification display.

“Sent to provider” means the SMTP server accepted the message, **not** confirmed inbox delivery. Check the email provider for downstream delivery failures. Retries are at least once: a worker crash or timeout after provider acceptance can produce a duplicate email. The same order reference identifies duplicates. Do not run a live test against the shop without arranging it with them.

## Validate

```powershell
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py test
.venv\Scripts\python.exe manage.py collectstatic --noinput
```

The order tests use Django's temporary database and in-memory email. They cover totals, quantity limits, invalid input, idempotency, rollback, receipt privacy, CSRF, staff permissions/status transitions, email failures and retries, and isolation of historical non-email jobs. They do not send real emails.

## Deployment

Set `DJANGO_DEBUG=0`, a private `DJANGO_SECRET_KEY`, and a comma-separated `DJANGO_ALLOWED_HOSTS` list for your hostname. In production, serve over HTTPS; session and CSRF cookies are secure when debug is off. Run migrations and `collectstatic`, configure your web server to serve `staticfiles/` at `/static/`, and run `config.wsgi:application` or `config.asgi:application` with a production server. Do not deploy with Django's development `runserver`. Keep the SQLite database outside ephemeral storage and back it up, or configure a production database.

The original sample menu remains in historical migrations and `content.json`; it is not the live menu after `import_shop_menu --apply`. Apply the supplied source menu on a new installation before taking orders. Later product and price edits are managed in the admin.

## Migration backup

The original React source and configuration are saved in `.migration-backups/react-before-django.zip` (ignored by git). Unzip to a separate folder to inspect the previous implementation. The original image assets remain in `public/`.
