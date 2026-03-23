import json
import csv
from datetime import datetime
from pathlib import Path
import re
import time
import os
import argparse
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
    "discord_resend_minutes": 180,
    "notify_on_existing_alert": os.environ.get("NOTIFY_ON_EXISTING_ALERT", "false").lower() in ("1", "true", "yes"),
    "headless": os.environ.get("HEADLESS", "false").lower() in ("1", "true", "yes"),
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
    
    def log(self, message):
        """Log messages to file and console"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message)
        
        with open(self.log_file, 'a') as f:
            f.write(log_message + "\n")
    
    def send_discord_alert(self, node_name, cpu, ram, alerts, url):
        """Send alert to Discord webhook"""
        try:
            if not CONFIG["discord_webhook"]:
                self.log("DISCORD_WEBHOOK is not set. Skipping Discord notification.")
                return

            # Create an embed for Discord
            embed = {
                "title": "[OUT OF STOCK] Node Alert",
                "description": f"Node: **{node_name}**",
                "color": 16711680,  # Red color
                "fields": [
                    {
                        "name": "CPU Usage (72h max)",
                        "value": f"**{cpu}%** ⚠️" if cpu >= CONFIG["cpu_threshold"] else f"{cpu}%",
                        "inline": True
                    },
                    {
                        "name": "RAM Usage (72h max)",
                        "value": f"**{ram}%** ⚠️" if ram >= CONFIG["ram_threshold"] else f"{ram}%",
                        "inline": True
                    },
                    {
                        "name": "Thresholds",
                        "value": f"CPU: {CONFIG['cpu_threshold']}% | RAM: {CONFIG['ram_threshold']}%",
                        "inline": False
                    },
                    {
                        "name": "Alerts",
                        "value": "\n".join([f"🔴 {alert}" for alert in alerts]),
                        "inline": False
                    },
                    {
                        "name": "Status Page",
                        "value": f"[View Details]({url})",
                        "inline": False
                    }
                ],
                "timestamp": datetime.now().isoformat(),
                "footer": {
                    "text": "ATBPHosting Monitor"
                }
            }
            
            payload = {
                "embeds": [embed],
                "username": "ATBPHosting Monitor"
            }
            
            response = requests.post(CONFIG["discord_webhook"], json=payload, timeout=10)
            
            if response.status_code == 204:
                self.log("Discord notification sent successfully")
            else:
                self.log(f"Failed to send Discord notification: {response.status_code} | body: {response.text}")
        
        except Exception as e:
            self.log(f"Error sending Discord notification: {e}")

    def _build_driver(self):
        """Create a configured Chrome driver instance."""
        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
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

            # Wait for page to load
            time.sleep(2)

            # Find and click the 72h buttons for CPU and RAM
            try:
                buttons_72h = driver.find_elements(By.XPATH, "//button[contains(text(), '72h')] | //*[contains(text(), '72h')][contains(@role, 'button')]")

                for button in buttons_72h:
                    try:
                        driver.execute_script("arguments[0].scrollIntoView(true);", button)
                        time.sleep(0.25)
                        button.click()
                        self.log("Clicked 72h button")
                        time.sleep(0.6)
                    except Exception:
                        pass
            except Exception as e:
                self.log(f"Warning: Could not click 72h buttons: {e}")

            # Wait for page to render metrics
            time.sleep(1.5)

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
    
    def check_thresholds(self, metrics):
        """Check if metrics exceed thresholds"""
        alerts = []
        
        cpu_max = metrics["cpu"]["max"]
        ram_max = metrics["ram"]["max"]
        
        if cpu_max >= CONFIG["cpu_threshold"]:
            alerts.append(f"CPU exceeded threshold: {cpu_max}%")
        
        if ram_max >= CONFIG["ram_threshold"]:
            alerts.append(f"RAM exceeded threshold: {ram_max}%")
        
        return alerts
    
    def save_metrics(self, metrics, alerts):
        """Save metrics to CSV and update stock status"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        node = metrics["node_name"]
        cpu = metrics["cpu"]["max"]
        ram = metrics["ram"]["max"]
        status = "OUT_OF_STOCK" if alerts else "IN_STOCK"
        
        # Save to CSV
        with open(self.history_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, node, cpu, ram, status])
        
        # Update stock status
        if alerts:
            with open(self.stock_status_file, 'r') as f:
                stock_data = json.load(f)
            
            entry = {
                "node": node,
                "timestamp": timestamp,
                "cpu": cpu,
                "ram": ram,
                "alerts": alerts,
                "detected_at": timestamp,
                "last_notified_at": timestamp,
                "note": "Max value in past 72 hours - may have occurred before monitoring started"
            }
            
            # Check if this node is already marked as out of stock to avoid spam
            existing_entry = next((item for item in stock_data["out_of_stock"] if item.get("node") == node), None)
            
            if not existing_entry:
                stock_data["out_of_stock"].append(entry)
                self.log(f"[ALERT] OUT-OF-STOCK NODE DETECTED: {node}")
                
                # Send Discord notification
                self.send_discord_alert(node, cpu, ram, alerts, metrics.get("url", "N/A"))
            else:
                if CONFIG["notify_on_existing_alert"]:
                    self.log(f"[ALERT] Forced notification for existing out-of-stock node: {node}")
                    self.send_discord_alert(node, cpu, ram, alerts, metrics.get("url", "N/A"))
                    existing_entry["last_notified_at"] = timestamp
                    with open(self.stock_status_file, 'w') as f:
                        json.dump(stock_data, f, indent=2)
                    return

                # Re-notify every N minutes while still above threshold.
                notify_at = existing_entry.get("last_notified_at") or existing_entry.get("timestamp")
                try:
                    last_notify_dt = datetime.strptime(notify_at, "%Y-%m-%d %H:%M:%S")
                    minutes_since = (datetime.now() - last_notify_dt).total_seconds() / 60.0
                except Exception:
                    minutes_since = CONFIG["discord_resend_minutes"] + 1

                if minutes_since >= CONFIG["discord_resend_minutes"]:
                    self.log(f"[ALERT] Re-notifying Discord for node still out of stock: {node}")
                    self.send_discord_alert(node, cpu, ram, alerts, metrics.get("url", "N/A"))
                    existing_entry["last_notified_at"] = timestamp
            
            with open(self.stock_status_file, 'w') as f:
                json.dump(stock_data, f, indent=2)

    def run_once(self):
        """Run one full monitoring pass across all URLs."""
        self.log("Starting one-time monitoring run...")
        self.log(f"Monitoring {len(CONFIG['urls'])} URLs")
        self.log(f"CPU threshold: {CONFIG['cpu_threshold']}%")
        self.log(f"RAM threshold: {CONFIG['ram_threshold']}%")

        driver = None
        try:
            driver = self._build_driver()
            for url in CONFIG['urls']:
                metrics = self.scrape_metrics_with_driver(driver, url)

                if metrics:
                    alerts = self.check_thresholds(metrics)
                    self.save_metrics(metrics, alerts)

                    self.log(f"Node: {metrics['node_name']}")
                    self.log(f"CPU: {metrics['cpu']['current']}% (Max: {metrics['cpu']['max']}%)")
                    self.log(f"RAM: {metrics['ram']['current']}% (Max: {metrics['ram']['max']}%)")

                    if alerts:
                        self.log(f"[ALERT] ALERTS: {'; '.join(alerts)}")
                        self.log("Status: OUT OF STOCK")
                    else:
                        self.log("Status: IN STOCK")

                    self.log("-" * 50)
        finally:
            if driver:
                driver.quit()
    
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

                driver = self._build_driver()
                try:
                    # Check all URLs
                    for url in CONFIG['urls']:
                        metrics = self.scrape_metrics_with_driver(driver, url)
                        
                        if metrics:
                            alerts = self.check_thresholds(metrics)
                            self.save_metrics(metrics, alerts)
                            
                            self.log(f"Node: {metrics['node_name']}")
                            self.log(f"CPU: {metrics['cpu']['current']}% (Max: {metrics['cpu']['max']}%)")
                            self.log(f"RAM: {metrics['ram']['current']}% (Max: {metrics['ram']['max']}%)")
                            
                            if alerts:
                                self.log(f"[ALERT] ALERTS: {'; '.join(alerts)}")
                                self.log("Status: OUT OF STOCK")
                            else:
                                self.log("Status: IN STOCK")
                            
                            self.log("-" * 50)
                finally:
                    driver.quit()
                
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
