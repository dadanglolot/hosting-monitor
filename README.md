# HetrixTools Continuous Monitor

Automated monitoring system for ATBPHosting's HetrixTools status page to track CPU/RAM usage and identify out-of-stock nodes.

## Features

- ✅ **Continuous Monitoring** - Checks metrics every hour (configurable)
- ✅ **CPU/RAM Tracking** - Monitors max, current, and average usage over 72 hours
- ✅ **Threshold Alerts** - Flags nodes exceeding 90% (configurable)
- ✅ **Out of Stock Detection** - Auto-marks nodes that exceed limits
- ✅ **Data Storage** - Saves all metrics to CSV and JSON
- ✅ **Logging** - Full activity logs for troubleshooting
- ✅ **Windows Integration** - Easy Task Scheduler setup

## Installation

### 1. Install Python
Download Python 3.8+ from https://www.python.org/downloads/
**Important:** Check "Add Python to PATH" during installation

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

This installs:
- Selenium (web scraping)
- WebDriver Manager (automatic Chrome driver)

### 3. Setup

#### Option A: Manual Run
```bash
python monitor.py
```

#### Option B: Windows Task Scheduler (Recommended for continuous monitoring)
```bash
setup_scheduler.bat
```
This will prompt you to choose a monitoring interval.

## Configuration

Edit `monitor.py` to change settings:

```python
CONFIG = {
    "url": "https://status.atbphosting.com/report/uptime/df035459a3513ae69d3414c3e8827e36/",
    "check_interval": 3600,  # seconds (3600 = 1 hour)
    "cpu_threshold": 90,     # percentage
    "ram_threshold": 90,     # percentage
    "data_dir": "monitoring_data",
}
```

## Output Files

### monitoring_data/
- **monitor.log** - Detailed activity log
- **history.csv** - Historical metrics (timestamp, node, CPU, RAM, status)
- **stock_status.json** - List of out-of-stock nodes with alerts

## Example Usage

### Initial setup:
```bash
# Install dependencies
pip install -r requirements.txt

# Test the monitor
python monitor.py

# After confirming it works, schedule it
setup_scheduler.bat
```

### View monitoring results:
```bash
# Check stock status
type monitoring_data\stock_status.json

# View history
type monitoring_data\history.csv

# Follow live logs
type monitoring_data\monitor.log
```

## Troubleshooting

### "Python is not found"
- Make sure Python is installed and added to PATH
- Restart your terminal after installing Python

### "Selenium errors"
- Re-install Selenium: `pip install --upgrade selenium`
- Ensure Chrome is installed on your system

### Task Scheduler not working
- Run `setup_scheduler.bat` as Administrator
-Check Task Scheduler logs: `Event Viewer → Windows Logs → System`

## Support

For issues or customization, check the monitoring log:
```bash
monitoring_data\monitor.log
```

---

**Status:** Ready for continuous automated monitoring
