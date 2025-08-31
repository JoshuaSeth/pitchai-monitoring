#!/usr/bin/env python3
"""
AutoPAR Staging Log Analyzer

Specialized log analysis for AutoPAR staging environment:
- Analyzes autopar-webapp-test container logs
- Detects PAR analysis pipeline issues
- Monitors WebSocket connections and HTMX functionality
- Identifies authentication and session problems
- Tracks 3D model processing and inference errors
"""

import json
import os
import re
import subprocess
import sys
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add current directory to path for imports
sys.path.append('.')

from monitoring.log_collector.docker_logs import BashDockerLogCollector, LogEntry


class AutoPARLogAnalyzer:
    """Specialized log analyzer for AutoPAR staging environment."""
    
    def __init__(self, hours_back: int = 4):
        """Initialize the AutoPAR log analyzer.
        
        Args:
            hours_back: Hours of logs to analyze (default: 4)
        """
        self.hours_back = hours_back
        self.timestamp = datetime.utcnow()
        self.config = self._load_autopar_config()
        self.collector = BashDockerLogCollector()
        
        # AutoPAR-specific patterns
        self.autopar_containers = ["autopar-webapp-test", "autopar-redis", "autopar-rabbitmq"]
        self.analysis_results = {}
        
    def _load_autopar_config(self) -> dict:
        """Load AutoPAR-specific monitoring configuration."""
        config_path = Path("config/autopar-staging-monitoring.yaml")
        if config_path.exists():
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        return {}
    
    def get_autopar_containers_status(self) -> Dict[str, dict]:
        """Get status of all AutoPAR-related containers."""
        print("🐳 Checking AutoPAR container status...")
        
        container_status = {}
        
        # Get all containers (running and stopped)
        try:
            result = subprocess.run([
                "docker", "ps", "-a", "--format", "json"
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            container_info = json.loads(line)
                            name = container_info.get("Names", "")
                            
                            # Check if this is an AutoPAR container
                            if any(pattern in name.lower() for pattern in ["autopar", "rabbitmq", "redis"]):
                                container_status[name] = {
                                    "name": name,
                                    "image": container_info.get("Image", ""),
                                    "status": container_info.get("Status", ""),
                                    "state": container_info.get("State", ""),
                                    "ports": container_info.get("Ports", ""),
                                    "is_running": "Up" in container_info.get("Status", ""),
                                    "health": self._extract_health_status(container_info.get("Status", ""))
                                }
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            print(f"  ❌ Error checking container status: {e}")
            
        print(f"  📊 Found {len(container_status)} AutoPAR-related containers")
        return container_status
    
    def _extract_health_status(self, status_string: str) -> str:
        """Extract health status from container status string."""
        if "healthy" in status_string.lower():
            return "healthy"
        elif "unhealthy" in status_string.lower():
            return "unhealthy"
        elif "starting" in status_string.lower():
            return "starting"
        else:
            return "unknown"
    
    def analyze_autopar_webapp_logs(self) -> Dict[str, any]:
        """Analyze logs from the AutoPAR webapp container."""
        print("🔍 Analyzing AutoPAR webapp logs...")
        
        webapp_analysis = {
            "container_name": "autopar-webapp-test",
            "log_entries_found": 0,
            "errors": [],
            "warnings": [],
            "performance_issues": [],
            "par_analysis_issues": [],
            "websocket_issues": [],
            "authentication_issues": [],
            "model_processing_issues": [],
            "summary": {}
        }
        
        # Check if webapp container exists and get logs
        try:
            since = self.timestamp - timedelta(hours=self.hours_back)
            logs = self.collector.get_container_logs("autopar-webapp-test", since=since)
            webapp_analysis["log_entries_found"] = len(logs)
            
            if not logs:
                webapp_analysis["summary"]["status"] = "no_logs"
                webapp_analysis["summary"]["message"] = "Container not running or no logs available"
                return webapp_analysis
            
            # Analyze each log entry
            for log_entry in logs:
                self._analyze_autopar_log_entry(log_entry, webapp_analysis)
                
            # Generate summary
            webapp_analysis["summary"] = self._generate_webapp_summary(webapp_analysis)
            
        except Exception as e:
            webapp_analysis["summary"]["status"] = "error"
            webapp_analysis["summary"]["message"] = f"Failed to analyze logs: {str(e)}"
            
        return webapp_analysis
    
    def _analyze_autopar_log_entry(self, log_entry: LogEntry, analysis: dict):
        """Analyze a single log entry for AutoPAR-specific patterns."""
        message = log_entry.message.lower()
        
        # Error pattern detection
        error_patterns = self.config.get("container_monitoring", {}).get("autopar_error_keywords", [])
        for pattern in error_patterns:
            if re.search(pattern.lower(), message):
                analysis["errors"].append({
                    "timestamp": log_entry.timestamp.isoformat(),
                    "message": log_entry.message[:200],
                    "pattern": pattern,
                    "level": log_entry.level or "ERROR"
                })
                break
        
        # Warning pattern detection
        warning_patterns = self.config.get("container_monitoring", {}).get("autopar_warning_keywords", [])
        for pattern in warning_patterns:
            if re.search(pattern.lower(), message):
                analysis["warnings"].append({
                    "timestamp": log_entry.timestamp.isoformat(),
                    "message": log_entry.message[:200],
                    "pattern": pattern,
                    "level": log_entry.level or "WARNING"
                })
                break
        
        # PAR analysis specific issues
        par_patterns = ["par.*failed", "analysis.*error", "pipeline.*failed", "inference.*failed"]
        for pattern in par_patterns:
            if re.search(pattern, message):
                analysis["par_analysis_issues"].append({
                    "timestamp": log_entry.timestamp.isoformat(),
                    "message": log_entry.message[:200],
                    "type": "par_analysis_error"
                })
                break
        
        # WebSocket issues
        ws_patterns = ["websocket.*error", "websocket.*failed", "ws.*connection.*lost"]
        for pattern in ws_patterns:
            if re.search(pattern, message):
                analysis["websocket_issues"].append({
                    "timestamp": log_entry.timestamp.isoformat(),
                    "message": log_entry.message[:200],
                    "type": "websocket_error"
                })
                break
        
        # Authentication issues
        auth_patterns = ["authentication.*failed", "session.*expired", "token.*invalid", "401", "403"]
        for pattern in auth_patterns:
            if re.search(pattern, message):
                analysis["authentication_issues"].append({
                    "timestamp": log_entry.timestamp.isoformat(),
                    "message": log_entry.message[:200],
                    "type": "authentication_error"
                })
                break
        
        # Model processing issues
        model_patterns = ["model.*error", "3d.*model.*failed", "gpu.*allocation.*failed", "inference.*timeout"]
        for pattern in model_patterns:
            if re.search(pattern, message):
                analysis["model_processing_issues"].append({
                    "timestamp": log_entry.timestamp.isoformat(),
                    "message": log_entry.message[:200],
                    "type": "model_processing_error"
                })
                break
    
    def _generate_webapp_summary(self, analysis: dict) -> dict:
        """Generate a summary of webapp log analysis."""
        total_issues = (len(analysis["errors"]) + 
                       len(analysis["warnings"]) + 
                       len(analysis["par_analysis_issues"]) + 
                       len(analysis["websocket_issues"]) + 
                       len(analysis["authentication_issues"]) + 
                       len(analysis["model_processing_issues"]))
        
        if len(analysis["errors"]) >= 5 or len(analysis["par_analysis_issues"]) >= 3:
            status = "critical"
            severity = "HIGH"
        elif total_issues >= 10 or len(analysis["errors"]) >= 1:
            status = "suspicious" 
            severity = "MEDIUM"
        else:
            status = "healthy"
            severity = "LOW"
        
        return {
            "status": status,
            "severity": severity,
            "total_log_entries": analysis["log_entries_found"],
            "total_issues": total_issues,
            "error_count": len(analysis["errors"]),
            "warning_count": len(analysis["warnings"]),
            "par_issues": len(analysis["par_analysis_issues"]),
            "websocket_issues": len(analysis["websocket_issues"]),
            "auth_issues": len(analysis["authentication_issues"]),
            "model_issues": len(analysis["model_processing_issues"])
        }
    
    def analyze_redis_logs(self) -> Dict[str, any]:
        """Analyze Redis container logs for AutoPAR connectivity."""
        print("🔍 Analyzing AutoPAR Redis logs...")
        
        redis_analysis = {
            "container_name": "autopar-redis",
            "log_entries_found": 0,
            "connection_issues": [],
            "performance_warnings": [],
            "errors": [],
            "summary": {}
        }
        
        try:
            since = self.timestamp - timedelta(hours=self.hours_back)
            logs = self.collector.get_container_logs("autopar-redis", since=since)
            redis_analysis["log_entries_found"] = len(logs)
            
            if not logs:
                redis_analysis["summary"]["status"] = "no_logs"
                return redis_analysis
                
            # Analyze Redis-specific patterns
            for log_entry in logs:
                message = log_entry.message.lower()
                
                # Connection issues
                if any(pattern in message for pattern in ["connection", "client", "timeout"]):
                    if any(error in message for error in ["error", "failed", "refused"]):
                        redis_analysis["connection_issues"].append({
                            "timestamp": log_entry.timestamp.isoformat(),
                            "message": log_entry.message[:200]
                        })
                
                # Performance warnings  
                if any(pattern in message for pattern in ["slow", "memory", "warning"]):
                    redis_analysis["performance_warnings"].append({
                        "timestamp": log_entry.timestamp.isoformat(),
                        "message": log_entry.message[:200]
                    })
                
                # General errors
                if log_entry.level == "ERROR" or any(pattern in message for pattern in ["error", "fatal"]):
                    redis_analysis["errors"].append({
                        "timestamp": log_entry.timestamp.isoformat(),
                        "message": log_entry.message[:200]
                    })
                    
            redis_analysis["summary"] = self._generate_redis_summary(redis_analysis)
            
        except Exception as e:
            redis_analysis["summary"]["status"] = "error"
            redis_analysis["summary"]["message"] = str(e)
            
        return redis_analysis
    
    def _generate_redis_summary(self, analysis: dict) -> dict:
        """Generate Redis analysis summary."""
        total_issues = len(analysis["connection_issues"]) + len(analysis["errors"])
        
        if len(analysis["errors"]) >= 3 or len(analysis["connection_issues"]) >= 5:
            status = "critical"
        elif total_issues > 0 or len(analysis["performance_warnings"]) >= 3:
            status = "suspicious"
        else:
            status = "healthy"
            
        return {
            "status": status,
            "total_issues": total_issues,
            "connection_issues": len(analysis["connection_issues"]),
            "performance_warnings": len(analysis["performance_warnings"]),
            "errors": len(analysis["errors"])
        }
    
    def analyze_rabbitmq_logs(self) -> Dict[str, any]:
        """Analyze RabbitMQ container logs for AutoPAR message queue."""
        print("🔍 Analyzing AutoPAR RabbitMQ logs...")
        
        rabbitmq_analysis = {
            "container_name": "autopar-rabbitmq", 
            "log_entries_found": 0,
            "connection_issues": [],
            "queue_issues": [],
            "errors": [],
            "summary": {}
        }
        
        try:
            since = self.timestamp - timedelta(hours=self.hours_back)
            logs = self.collector.get_container_logs("autopar-rabbitmq", since=since)
            rabbitmq_analysis["log_entries_found"] = len(logs)
            
            if not logs:
                rabbitmq_analysis["summary"]["status"] = "no_logs"
                return rabbitmq_analysis
                
            # Analyze RabbitMQ-specific patterns
            for log_entry in logs:
                message = log_entry.message.lower()
                
                # Connection issues
                if any(pattern in message for pattern in ["connection", "client.*disconnect", "tcp.*closed"]):
                    if any(error in message for error in ["error", "failed", "unexpected"]):
                        rabbitmq_analysis["connection_issues"].append({
                            "timestamp": log_entry.timestamp.isoformat(),
                            "message": log_entry.message[:200]
                        })
                
                # Queue issues
                if any(pattern in message for pattern in ["queue", "message.*lost", "delivery.*failed"]):
                    rabbitmq_analysis["queue_issues"].append({
                        "timestamp": log_entry.timestamp.isoformat(),
                        "message": log_entry.message[:200]
                    })
                
                # General errors
                if log_entry.level == "ERROR" or any(pattern in message for pattern in ["error", "fatal", "crash"]):
                    rabbitmq_analysis["errors"].append({
                        "timestamp": log_entry.timestamp.isoformat(),
                        "message": log_entry.message[:200]
                    })
                    
            rabbitmq_analysis["summary"] = self._generate_rabbitmq_summary(rabbitmq_analysis)
            
        except Exception as e:
            rabbitmq_analysis["summary"]["status"] = "error"
            rabbitmq_analysis["summary"]["message"] = str(e)
            
        return rabbitmq_analysis
    
    def _generate_rabbitmq_summary(self, analysis: dict) -> dict:
        """Generate RabbitMQ analysis summary."""
        total_issues = (len(analysis["connection_issues"]) + 
                       len(analysis["queue_issues"]) + 
                       len(analysis["errors"]))
        
        if len(analysis["errors"]) >= 3 or len(analysis["queue_issues"]) >= 2:
            status = "critical"
        elif total_issues > 0:
            status = "suspicious"
        else:
            status = "healthy"
            
        return {
            "status": status,
            "total_issues": total_issues,
            "connection_issues": len(analysis["connection_issues"]),
            "queue_issues": len(analysis["queue_issues"]),
            "errors": len(analysis["errors"])
        }
    
    def generate_comprehensive_autopar_report(self) -> str:
        """Generate a comprehensive AutoPAR staging monitoring report."""
        print("📋 Generating comprehensive AutoPAR staging report...")
        
        # Collect all analysis data
        container_status = self.get_autopar_containers_status()
        webapp_analysis = self.analyze_autopar_webapp_logs()
        redis_analysis = self.analyze_redis_logs()
        rabbitmq_analysis = self.analyze_rabbitmq_logs()
        
        # Determine overall health status
        overall_status = self._determine_overall_status(
            container_status, webapp_analysis, redis_analysis, rabbitmq_analysis
        )
        
        # Generate formatted report
        report = self._format_autopar_report(
            overall_status, container_status, webapp_analysis, 
            redis_analysis, rabbitmq_analysis
        )
        
        # Save report to file
        self._save_autopar_report(report)
        
        return report
    
    def _determine_overall_status(self, containers, webapp, redis, rabbitmq) -> dict:
        """Determine the overall health status of AutoPAR staging."""
        critical_issues = []
        suspicious_issues = []
        healthy_components = 0
        total_components = 0
        
        # Check container status
        for name, container in containers.items():
            total_components += 1
            if not container["is_running"]:
                critical_issues.append(f"Container {name} is not running")
            elif container["health"] == "unhealthy":
                critical_issues.append(f"Container {name} is unhealthy")
            elif container["health"] == "starting":
                suspicious_issues.append(f"Container {name} is still starting")
            else:
                healthy_components += 1
        
        # Check webapp analysis
        total_components += 1
        if webapp["summary"].get("status") == "critical":
            critical_issues.append("AutoPAR webapp has critical issues")
        elif webapp["summary"].get("status") == "suspicious":
            suspicious_issues.append("AutoPAR webapp has suspicious patterns")
        elif webapp["summary"].get("status") == "healthy":
            healthy_components += 1
        
        # Check Redis
        total_components += 1
        if redis["summary"].get("status") == "critical":
            critical_issues.append("Redis has critical issues")
        elif redis["summary"].get("status") == "suspicious":
            suspicious_issues.append("Redis has suspicious patterns")
        elif redis["summary"].get("status") == "healthy":
            healthy_components += 1
        
        # Check RabbitMQ
        total_components += 1
        if rabbitmq["summary"].get("status") == "critical":
            critical_issues.append("RabbitMQ has critical issues")
        elif rabbitmq["summary"].get("status") == "suspicious":
            suspicious_issues.append("RabbitMQ has suspicious patterns")
        elif rabbitmq["summary"].get("status") == "healthy":
            healthy_components += 1
        
        # Determine overall status
        if len(critical_issues) > 0:
            overall_status = "ERRORS_INVESTIGATE"
        elif len(suspicious_issues) > 0:
            overall_status = "SUSPICIOUS_INVESTIGATE"
        else:
            overall_status = "ALL_GOOD"
        
        health_score = (healthy_components / total_components * 100) if total_components > 0 else 0
        
        return {
            "status": overall_status,
            "health_score": health_score,
            "critical_issues": critical_issues,
            "suspicious_issues": suspicious_issues,
            "healthy_components": healthy_components,
            "total_components": total_components
        }
    
    def _format_autopar_report(self, overall_status, containers, webapp, redis, rabbitmq) -> str:
        """Format the comprehensive AutoPAR report."""
        timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        report = f"""
================================================================================
AUTOPAR STAGING ENVIRONMENT MONITORING REPORT
================================================================================
Report Generated: {timestamp_str}
Analysis Period: {self.hours_back} hours
Environment: staging.autopar.pitchai.net
Overall Status: {overall_status["status"]}
Health Score: {overall_status["health_score"]:.1f}/100

================================================================================
EXECUTIVE SUMMARY
================================================================================
Components Analyzed: {overall_status["total_components"]}
Healthy Components: {overall_status["healthy_components"]}
Critical Issues: {len(overall_status["critical_issues"])}
Suspicious Patterns: {len(overall_status["suspicious_issues"])}

"""

        # Add critical issues if any
        if overall_status["critical_issues"]:
            report += "🚨 CRITICAL ISSUES REQUIRING IMMEDIATE ATTENTION:\n"
            for issue in overall_status["critical_issues"]:
                report += f"   • {issue}\n"
            report += "\n"
        
        # Add suspicious issues if any
        if overall_status["suspicious_issues"]:
            report += "⚠️  SUSPICIOUS PATTERNS REQUIRING INVESTIGATION:\n"
            for issue in overall_status["suspicious_issues"]:
                report += f"   • {issue}\n"
            report += "\n"

        # Container Status Section
        report += """================================================================================
DOCKER CONTAINER STATUS
================================================================================
"""
        for name, container in containers.items():
            status_emoji = "✅" if container["is_running"] else "❌"
            health_emoji = {"healthy": "🟢", "unhealthy": "🔴", "starting": "🟡", "unknown": "⚪"}
            
            report += f"""
Container: {name}
Status: {status_emoji} {container['status']}
Health: {health_emoji.get(container['health'], '⚪')} {container['health']}
Image: {container['image']}
Ports: {container['ports']}
"""

        # Webapp Analysis Section
        report += f"""
================================================================================
AUTOPAR WEBAPP LOG ANALYSIS
================================================================================
Container: {webapp['container_name']}
Log Entries Analyzed: {webapp['log_entries_found']}
Status: {webapp['summary'].get('status', 'unknown').upper()}

Error Summary:
• Total Errors: {webapp['summary'].get('error_count', 0)}
• PAR Analysis Issues: {webapp['summary'].get('par_issues', 0)}
• WebSocket Issues: {webapp['summary'].get('websocket_issues', 0)}
• Authentication Issues: {webapp['summary'].get('auth_issues', 0)}
• Model Processing Issues: {webapp['summary'].get('model_issues', 0)}
"""

        # Recent errors
        if webapp["errors"]:
            report += "\nRecent Errors (Last 5):\n"
            for error in webapp["errors"][-5:]:
                report += f"• [{error['timestamp']}] {error['message']}\n"

        # Redis Analysis Section
        report += f"""
================================================================================
REDIS LOG ANALYSIS  
================================================================================
Container: {redis['container_name']}
Log Entries Analyzed: {redis['log_entries_found']}
Status: {redis['summary'].get('status', 'unknown').upper()}

Issue Summary:
• Connection Issues: {redis['summary'].get('connection_issues', 0)}
• Performance Warnings: {redis['summary'].get('performance_warnings', 0)}
• Errors: {redis['summary'].get('errors', 0)}
"""

        # RabbitMQ Analysis Section
        report += f"""
================================================================================
RABBITMQ LOG ANALYSIS
================================================================================
Container: {rabbitmq['container_name']}
Log Entries Analyzed: {rabbitmq['log_entries_found']}
Status: {rabbitmq['summary'].get('status', 'unknown').upper()}

Issue Summary:
• Connection Issues: {rabbitmq['summary'].get('connection_issues', 0)}
• Queue Issues: {rabbitmq['summary'].get('queue_issues', 0)}
• Errors: {rabbitmq['summary'].get('errors', 0)}
"""

        # Recommendations Section
        report += """
================================================================================
RECOMMENDATIONS
================================================================================
"""
        if overall_status["status"] == "ERRORS_INVESTIGATE":
            report += """🚨 IMMEDIATE ACTION REQUIRED:
1. Investigate critical issues listed above
2. Check AutoPAR webapp container status
3. Verify database connectivity (Redis/RabbitMQ)
4. Monitor staging.autopar.pitchai.net accessibility
5. Review recent deployments or configuration changes

"""
        elif overall_status["status"] == "SUSPICIOUS_INVESTIGATE":
            report += """⚠️  MONITORING RECOMMENDED:
1. Keep monitoring suspicious patterns
2. Check performance metrics
3. Verify all services are responding normally
4. Consider preventive maintenance if patterns persist

"""
        else:
            report += """✅ SYSTEM HEALTHY:
1. Continue regular monitoring
2. All AutoPAR components operating normally
3. No immediate action required

"""

        report += f"""
================================================================================
NEXT MONITORING CHECK: {(self.timestamp + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S UTC')}
================================================================================
"""

        return report
    
    def _save_autopar_report(self, report: str):
        """Save the AutoPAR report to file."""
        # Create autopar-staging reports directory
        reports_dir = Path("reports/autopar-staging")
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp_str = self.timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"autopar_staging_report_{timestamp_str}.txt"
        filepath = reports_dir / filename
        
        # Save report
        with open(filepath, 'w') as f:
            f.write(report)
        
        print(f"📄 Report saved to: {filepath}")
        
        # Also save as latest report
        latest_filepath = reports_dir / "latest_autopar_report.txt"
        with open(latest_filepath, 'w') as f:
            f.write(report)


def main():
    """Main execution function for AutoPAR log analyzer."""
    import argparse
    
    parser = argparse.ArgumentParser(description="AutoPAR Staging Log Analyzer")
    parser.add_argument("--hours", type=int, default=4,
                       help="Hours of logs to analyze (default: 4)")
    
    args = parser.parse_args()
    
    print("🦷 AutoPAR Staging Log Analyzer")
    print("=" * 50)
    
    analyzer = AutoPARLogAnalyzer(hours_back=args.hours)
    report = analyzer.generate_comprehensive_autopar_report()
    
    print("\n" + "=" * 50)
    print("✅ AutoPAR analysis completed successfully")
    print(f"📊 Report covers {args.hours} hours of monitoring data")
    

if __name__ == "__main__":
    main()