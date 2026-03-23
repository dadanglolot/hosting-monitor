import json
import csv
from datetime import datetime
from pathlib import Path
import re
import time
import os
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

# Configuration
CONFIG = {
    "urls": [
        "https://status.atbphosting.com/report/uptime/df035459a3513ae69d3414c3e8827e36/",
        "https://status.atbphosting.com/report/uptime/fd0aca597ea55cfe810e060f4d288ead/",
        "https://status.atbphosting.com/report/uptime/3e462b263ca13b30818fab8aff107a61/"
    ],
    "discord_webhook": os.environ.get("DISCORD_WEBHOOK", ""),
    "headless": os.environ.get("HEADLESS", "false").lower() in ("1", "true", "yes"),
    "max_workers": int(os.environ.get("MAX_WORKERS", "2")),
    "check_interval": 3600,  # 1 hour in seconds
    "cpu_threshold": 90,
    "ram_threshold": 90,
    "data_dir": "monitoring_data",
    "log_file": "monitoring_data/monitor.log"
}

class HostingMonitor:
    def __init__(self):
        self.data_dir = Path(CONFIG["data_dir"])
        self.data_dir.mkdir(exist_ok=True)
        self.log_file = Path(CONFIG["log_file"])
        self.stock_status_file = self.data_dir / "stock_status.json"
        self.history_file = self.data_dir / "history.csv"
        self.scan_history_file = self.data_dir / "scan_history.csv"
        self._init_files()
    
    def _init_files(self):
        """Initialize data files if they don't exist"""
        if not self.stock_status_file.exists():
            with open(self.stock_status_file, 'w') as f:
                json.dump({"out_of_stock": []}, f, indent=2)
        
        if not self.history_file.exists():
            with open(self.history_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "node_name", "cpu_usage", "ram_usage", "status"])

        if not self.scan_history_file.exists():
            with open(self.scan_history_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    "node_name",
                    "cpu_current",
                    "cpu_average_72h",
                    "cpu_max_72h",
                    "ram_current",
                    "ram_average_72h",
                    "ram_max_72h",
                    "cpu_between_scans",
                    "ram_between_scans",
                    "status"
                ])
    
    def log(self, message):
        """Log messages to file and console"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message)
        
        with open(self.log_file, 'a') as f:
            f.write(log_message + "\n")
    
    def send_discord_scan_summary(self, scan_results):
        """Send one combined Discord webhook per scan."""
        try:
            if not CONFIG["discord_webhook"]:
                self.log("DISCORD_WEBHOOK is not set. Skipping Discord notification.")
                return

            out_count = sum(1 for item in scan_results if item["status"] == "OUT_OF_STOCK")

            embed = {
                "title": "[ATBP] Node Scan Summary",
                "description": (
                    f"Nodes scanned: **{len(scan_results)}**\n"
                    f"Out of stock: **{out_count}**\n"
                    "Rule: Out of stock is based on **average between scans**, not max."
                ),
                "color": 16711680 if out_count > 0 else 5763719,
                "fields": [],
                "timestamp": datetime.now().isoformat(),
                "footer": {
                    "text": "ATBPHosting Monitor"
                }
            }

            for item in scan_results:
                node_status = "OUT OF STOCK" if item["status"] == "OUT_OF_STOCK" else "IN STOCK"
                node_icon = "🔴" if item["status"] == "OUT_OF_STOCK" else "🟢"
                field_value = (
                    f"{node_icon} **{node_status}**\n"
                    f"Current CPU/RAM: {item['cpu_current']}% / {item['ram_current']}%\n"
                    f"72h Avg CPU/RAM: {item['cpu_average_72h']}% / {item['ram_average_72h']}%\n"
                    f"72h Max CPU/RAM: {item['cpu_max_72h']}% / {item['ram_max_72h']}%\n"
                    f"Between-Scan Avg CPU/RAM: **{item['cpu_between_scans']}% / {item['ram_between_scans']}%**\n"
                    f"Source: {item['url']}"
                )
                embed["fields"].append({
                    "name": item["node_name"][:256],
                    "value": field_value[:1024],
                    "inline": False
                })
            
            payload = {
                "embeds": [embed],
                "username": "ATBPHosting Monitor"
            }
            
            response = requests.post(CONFIG["discord_webhook"], json=payload, timeout=10)
            
            if response.status_code == 204:
                self.log("Discord scan summary sent successfully")
            else:
                self.log(f"Failed to send Discord summary: {response.status_code} | body: {response.text}")
        
        except Exception as e:
            self.log(f"Error sending Discord summary: {e}")

    def scrape_all_parallel(self):
        """Scrape all URLs in parallel and return successful metric results."""
        results = []
        max_workers = max(1, min(CONFIG["max_workers"], len(CONFIG["urls"])))
        self.log(f"Starting parallel scraping with {max_workers} workers...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self.scrape_metrics, url) for url in CONFIG["urls"]]
            for future in as_completed(futures):
                try:
                    metrics = future.result()
                    if metrics:
                        results.append(metrics)
                except Exception as e:
                    self.log(f"Parallel scrape task failed: {e}")

        return results

    def _build_driver(self):
        """Create a configured Chrome driver instance."""
        chrome_options = Options()
        chrome_options.set_capability("pageLoadStrategy", "eager")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-background-networking")
        chrome_options.add_argument("--disable-sync")
        chrome_options.add_argument("--disable-default-apps")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_experimental_option("prefs", {
            "profile.managed_default_content_settings.images": 2
        })
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        if CONFIG["headless"]:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
        return webdriver.Chrome(options=chrome_options)

    def scrape_metrics_with_driver(self, driver, url):
        """Scrape CPU and RAM metrics from HetrixTools using an existing driver."""
        try:
            self.log(f"Starting scrape for: {url}")

            driver.get(url)

            self.log("Page loaded, selecting 72-hour view...")

            # Wait until the page body is ready (faster than fixed sleeps).
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Find and click the 72h buttons for CPU and RAM
            try:
                buttons_72h = driver.find_elements(By.XPATH, "//button[contains(., '72h')] | //*[contains(., '72h')][contains(@role, 'button')]")

                # Limit clicks to first two controls (CPU + RAM) to avoid extra delays.
                buttons_72h = buttons_72h[:2]

                for button in buttons_72h:
                    try:
                        driver.execute_script("arguments[0].scrollIntoView(true);", button)
                        time.sleep(0.05)
                        button.click()
                        self.log("Clicked 72h button")
                        time.sleep(0.15)
                    except Exception:
                        pass
            except Exception as e:
                self.log(f"Warning: Could not click 72h buttons: {e}")

            # Small settle delay for chart values after the range switch.
            time.sleep(0.5)

            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            node_name = "Unknown"
            try:
                name_elements = soup.find_all(string=re.compile(r'sgp\.premium\.plus\.shared|\.shared\.'))
                if name_elements:
                    node_name = name_elements[0].strip()
            except Exception:
                pass

            cpu_data = self._parse_metrics(soup, "CPU")
            ram_data = self._parse_metrics(soup, "RAM")

            self.log(f"Successfully extracted metrics for {node_name} (72h view)")

            return {
                "node_name": node_name,
                "cpu": cpu_data,
                "ram": ram_data,
                "timestamp": datetime.now().isoformat(),
                "time_range": "72 hours",
                "url": url
            }

        except Exception as e:
            self.log(f"Error during scrape: {str(e)}")
            import traceback
            self.log(f"Traceback: {traceback.format_exc()}")
            return None
    
    def scrape_metrics(self, url):
        """Scrape CPU and RAM metrics from HetrixTools"""
        driver = None
        try:
            driver = self._build_driver()
            return self.scrape_metrics_with_driver(driver, url)
        finally:
            if driver:
                driver.quit()
    
    def _parse_metrics(self, soup, metric_type):
        """Parse metrics from HTML content"""
        try:
            # Get all text from the page
            page_text = soup.get_text()
            
            # Look for metrics like "Current CPU Usage 51.15%" or "Max CPU Usage 86.60%"
            current_pattern = rf'Current {metric_type}.*?(\d+\.?\d*)%'
            max_pattern = rf'Max {metric_type}.*?(\d+\.?\d*)%'
            avg_pattern = rf'Average {metric_type}.*?(\d+\.?\d*)%'
            
            # Extract current value
            current_match = re.search(current_pattern, page_text, re.IGNORECASE)
            current = float(current_match.group(1)) if current_match else 0
            
            # Extract max value
            max_match = re.search(max_pattern, page_text, re.IGNORECASE)
            max_val = float(max_match.group(1)) if max_match else 0
            
            # Extract average
            avg_match = re.search(avg_pattern, page_text, re.IGNORECASE)
            avg = float(avg_match.group(1)) if avg_match else 0
            
            if current > 0 or max_val > 0:
                self.log(f"{metric_type} - Current: {current}%, Max: {max_val}%, Average: {avg}%")
            else:
                self.log(f"Warning: No {metric_type} metrics found in page")
            
            return {
                "current": current,
                "max": max_val,
                "average": avg
            }
        except Exception as e:
            self.log(f"Error parsing {metric_type}: {e}")
            return {"current": 0, "max": 0, "average": 0}
    
    def calculate_between_scan_average(self, node_name, cpu_current, ram_current):
        """Calculate average usage between scans for the node using current values."""
        cpu_values = []
        ram_values = []

        if self.scan_history_file.exists():
            with open(self.scan_history_file, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("node_name") == node_name:
                        try:
                            cpu_values.append(float(row.get("cpu_current", 0) or 0))
                            ram_values.append(float(row.get("ram_current", 0) or 0))
                        except ValueError:
                            pass

        cpu_values.append(cpu_current)
        ram_values.append(ram_current)

        cpu_between = round(sum(cpu_values) / len(cpu_values), 2)
        ram_between = round(sum(ram_values) / len(ram_values), 2)
        return cpu_between, ram_between

    def check_thresholds(self, scan_record):
        """Check thresholds based on between-scan averages."""
        alerts = []

        if scan_record["cpu_between_scans"] >= CONFIG["cpu_threshold"]:
            alerts.append(f"CPU between-scan average exceeded threshold: {scan_record['cpu_between_scans']}%")

        if scan_record["ram_between_scans"] >= CONFIG["ram_threshold"]:
            alerts.append(f"RAM between-scan average exceeded threshold: {scan_record['ram_between_scans']}%")
        
        return alerts

    def build_scan_record(self, metrics):
        """Build a rich scan record including between-scan averages."""
        cpu_between, ram_between = self.calculate_between_scan_average(
            metrics["node_name"],
            metrics["cpu"]["current"],
            metrics["ram"]["current"]
        )

        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "node_name": metrics["node_name"],
            "cpu_current": metrics["cpu"]["current"],
            "cpu_average_72h": metrics["cpu"]["average"],
            "cpu_max_72h": metrics["cpu"]["max"],
            "ram_current": metrics["ram"]["current"],
            "ram_average_72h": metrics["ram"]["average"],
            "ram_max_72h": metrics["ram"]["max"],
            "cpu_between_scans": cpu_between,
            "ram_between_scans": ram_between,
            "url": metrics.get("url", "N/A")
        }
        alerts = self.check_thresholds(record)
        record["status"] = "OUT_OF_STOCK" if alerts else "IN_STOCK"
        record["alerts"] = alerts
        return record

    def save_metrics(self, scan_record):
        """Save detailed scan metrics and stock status."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        node = scan_record["node_name"]
        status = scan_record["status"]
        
        # Legacy CSV for backward compatibility
        with open(self.history_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, node, scan_record["cpu_max_72h"], scan_record["ram_max_72h"], status])

        # Detailed scan CSV
        with open(self.scan_history_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                scan_record["timestamp"],
                scan_record["node_name"],
                scan_record["cpu_current"],
                scan_record["cpu_average_72h"],
                scan_record["cpu_max_72h"],
                scan_record["ram_current"],
                scan_record["ram_average_72h"],
                scan_record["ram_max_72h"],
                scan_record["cpu_between_scans"],
                scan_record["ram_between_scans"],
                scan_record["status"]
            ])

        # Maintain latest out_of_stock snapshot based on current scan rule
        if self.stock_status_file.exists():
            with open(self.stock_status_file, 'r') as f:
                stock_data = json.load(f)
        else:
            stock_data = {"out_of_stock": []}

        if scan_record["status"] == "OUT_OF_STOCK":
            entry = {
                "node": scan_record["node_name"],
                "timestamp": scan_record["timestamp"],
                "cpu_between_scans": scan_record["cpu_between_scans"],
                "ram_between_scans": scan_record["ram_between_scans"],
                "cpu_current": scan_record["cpu_current"],
                "cpu_average_72h": scan_record["cpu_average_72h"],
                "cpu_max_72h": scan_record["cpu_max_72h"],
                "ram_current": scan_record["ram_current"],
                "ram_average_72h": scan_record["ram_average_72h"],
                "ram_max_72h": scan_record["ram_max_72h"],
                "alerts": scan_record["alerts"],
                "note": "Out-of-stock uses average between scans"
            }
            existing_index = next((i for i, item in enumerate(stock_data["out_of_stock"]) if item.get("node") == scan_record["node_name"]), None)
            if existing_index is None:
                stock_data["out_of_stock"].append(entry)
            else:
                stock_data["out_of_stock"][existing_index] = entry
        else:
            stock_data["out_of_stock"] = [
                item for item in stock_data["out_of_stock"]
                if item.get("node") != scan_record["node_name"]
            ]

        with open(self.stock_status_file, 'w') as f:
            json.dump(stock_data, f, indent=2)

    def run_once(self):
        """Run one full monitoring pass across all URLs."""
        self.log("Starting one-time monitoring run...")
        self.log(f"Monitoring {len(CONFIG['urls'])} URLs")
        self.log(f"CPU threshold: {CONFIG['cpu_threshold']}%")
        self.log(f"RAM threshold: {CONFIG['ram_threshold']}%")

        scan_results = []
        metrics_results = self.scrape_all_parallel()
        for metrics in metrics_results:
            scan_record = self.build_scan_record(metrics)
            self.save_metrics(scan_record)
            scan_results.append(scan_record)

            self.log(f"Node: {scan_record['node_name']}")
            self.log(f"CPU current/avg/max: {scan_record['cpu_current']}% / {scan_record['cpu_average_72h']}% / {scan_record['cpu_max_72h']}%")
            self.log(f"RAM current/avg/max: {scan_record['ram_current']}% / {scan_record['ram_average_72h']}% / {scan_record['ram_max_72h']}%")
            self.log(f"Between-scan avg CPU/RAM: {scan_record['cpu_between_scans']}% / {scan_record['ram_between_scans']}%")

            if scan_record["alerts"]:
                self.log(f"[ALERT] ALERTS: {'; '.join(scan_record['alerts'])}")
                self.log("Status: OUT OF STOCK")
            else:
                self.log("Status: IN STOCK")

            self.log("-" * 50)

        if scan_results:
            self.send_discord_scan_summary(scan_results)
    
    def run_continuous(self):
        """Run monitoring continuously"""
        self.log("Starting continuous monitoring...")
        self.log(f"Monitoring {len(CONFIG['urls'])} URLs")
        self.log(f"Check interval: {CONFIG['check_interval']} seconds")
        self.log(f"CPU threshold: {CONFIG['cpu_threshold']}%")
        self.log(f"RAM threshold: {CONFIG['ram_threshold']}%")
        
        check_count = 0
        while True:
            try:
                check_count += 1
                self.log(f"\n--- Check #{check_count} ---")
                scan_results = []

                metrics_results = self.scrape_all_parallel()
                for metrics in metrics_results:
                    scan_record = self.build_scan_record(metrics)
                    self.save_metrics(scan_record)
                    scan_results.append(scan_record)

                    self.log(f"Node: {scan_record['node_name']}")
                    self.log(f"CPU current/avg/max: {scan_record['cpu_current']}% / {scan_record['cpu_average_72h']}% / {scan_record['cpu_max_72h']}%")
                    self.log(f"RAM current/avg/max: {scan_record['ram_current']}% / {scan_record['ram_average_72h']}% / {scan_record['ram_max_72h']}%")
                    self.log(f"Between-scan avg CPU/RAM: {scan_record['cpu_between_scans']}% / {scan_record['ram_between_scans']}%")

                    if scan_record["alerts"]:
                        self.log(f"[ALERT] ALERTS: {'; '.join(scan_record['alerts'])}")
                        self.log("Status: OUT OF STOCK")
                    else:
                        self.log("Status: IN STOCK")

                    self.log("-" * 50)

                if scan_results:
                    self.send_discord_scan_summary(scan_results)
                
                self.log(f"Next check in {CONFIG['check_interval']} seconds...")
                time.sleep(CONFIG['check_interval'])
            
            except KeyboardInterrupt:
                self.log("Monitoring stopped by user")
                break
            except Exception as e:
                self.log(f"Error in monitoring loop: {e}")
                self.log(f"Retrying in 60 seconds...")
                time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATBPHosting monitor")
    parser.add_argument("--once", action="store_true", help="Run a single monitoring pass and exit")
    args = parser.parse_args()

    monitor = HostingMonitor()
    if args.once:
        monitor.run_once()
    else:
        monitor.run_continuous()
