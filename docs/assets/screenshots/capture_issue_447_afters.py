import os
import django

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["SECRET"] = "dev-screenshots"
django.setup()

from django.contrib.auth import get_user_model
from playwright.sync_api import sync_playwright

User = get_user_model()
demo_user = User.objects.filter(username="demo").first()
if not demo_user:
    demo_user = User.objects.create_user(username="demo", password="demodemo")
else:
    demo_user.set_password("demodemo")
    demo_user.theme = "light"
    demo_user.save()

screenshot_dir = "/home/ryan/code/Floppy/docs/assets/screenshots"
os.makedirs(screenshot_dir, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light")
    page = context.new_page()

    # Login to local dev server on port 8001
    page.goto("http://127.0.0.1:8001/accounts/login/")
    page.fill('input[name="login"]', "demo")
    page.fill('input[name="password"]', "demodemo")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    print("Logged in on port 8001. URL:", page.url)

    # 1. Import Data - Supported Import Formats (#9 in issue 447)
    page.goto("http://127.0.0.1:8001/settings/import", wait_until="networkidle")
    # Take screenshot of the import formats / documentation area
    page.screenshot(path=os.path.join(screenshot_dir, "01_import_formats_after.png"))
    print("Saved 01_import_formats_after.png")

    # 2. Integrations - Warning & Info boxes (#10 in issue 447)
    page.goto("http://127.0.0.1:8001/settings/integrations", wait_until="networkidle")
    page.screenshot(path=os.path.join(screenshot_dir, "02_integrations_warnings_after.png"))
    print("Saved 02_integrations_warnings_after.png")

    # 3. Advanced Settings - Clear All Caches (#447)
    page.goto("http://127.0.0.1:8001/settings/advanced", wait_until="networkidle")
    page.screenshot(path=os.path.join(screenshot_dir, "03_advanced_caches_after.png"))
    print("Saved 03_advanced_caches_after.png")

    # 4. Custom Lists - Dropdown & action items (#16 in issue 447)
    page.goto("http://127.0.0.1:8001/lists", wait_until="networkidle")
    page.screenshot(path=os.path.join(screenshot_dir, "04_lists_dropdown_after.png"))
    print("Saved 04_lists_dropdown_after.png")

    # 5. Home Screen / Media Library - Light theme
    page.goto("http://127.0.0.1:8001/", wait_until="networkidle")
    page.screenshot(path=os.path.join(screenshot_dir, "05_library_cards_after.png"))
    print("Saved 05_library_cards_after.png")

    browser.close()

print("Captured all matching after screenshots!")
