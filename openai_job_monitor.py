#!/usr/bin/env python3
"""
OpenAI Job Monitor - Enhanced with Job Lifecycle Tracking and CV Matching
Monitors OpenAI jobs via Ashby API, tracks job status, and scores matches against CV
"""

import requests
import json
import csv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import schedule
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional
import argparse
from job_matcher import JobMatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('openai_jobs.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class OpenAIJobMonitor:
    """Monitor OpenAI jobs using Ashby's public API with lifecycle tracking and CV matching"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.api_url = "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true"
        self.data_dir = Path("job_data")
        self.data_dir.mkdir(exist_ok=True)
        
        # Initialize job matcher
        self.job_matcher = JobMatcher(config.get('profile_path', 'profile.json'))
        
        # Files for tracking
        self.current_jobs_file = self.data_dir / "current_openai_jobs.json"
        self.master_database_file = self.data_dir / "openai_jobs_database.json"
        self.report_file = self.data_dir / f"openai_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        self.csv_file = self.data_dir / f"openai_jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    def fetch_jobs(self) -> Optional[List[Dict]]:
        """Fetch current jobs from OpenAI's Ashby API"""
        try:
            logger.info("Fetching jobs from OpenAI Ashby API...")
            response = requests.get(self.api_url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            jobs = data.get('jobs', [])
            
            logger.info(f"Successfully fetched {len(jobs)} jobs from API")
            return jobs
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch jobs from API: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse API response: {e}")
            return None
    
    def filter_san_francisco_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Filter jobs for San Francisco area"""
        sf_keywords = ['san francisco', 'sf', 'bay area']
        sf_jobs = []
        
        for job in jobs:
            # Check primary location
            location = job.get('location', '').lower()
            if any(keyword in location for keyword in sf_keywords):
                sf_jobs.append(job)
                continue
            
            # Check secondary locations
            secondary_locations = job.get('secondaryLocations', [])
            for sec_loc in secondary_locations:
                sec_location = sec_loc.get('location', '').lower()
                if any(keyword in sec_location for keyword in sf_keywords):
                    sf_jobs.append(job)
                    break
            
            # Check if job is remote (could be relevant)
            if job.get('isRemote', False) and 'remote' in self.config.get('include_remote', []):
                sf_jobs.append(job)
        
        logger.info(f"Filtered to {len(sf_jobs)} San Francisco area jobs")
        return sf_jobs
    
    def load_job_database(self) -> List[Dict]:
        """Load the master job database"""
        if not self.master_database_file.exists():
            return []
        
        try:
            with open(self.master_database_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load job database: {e}")
            return []
    
    def save_job_database(self, jobs: List[Dict]):
        """Save the master job database"""
        try:
            with open(self.master_database_file, 'w') as f:
                json.dump(jobs, f, indent=2)
            logger.info(f"Saved {len(jobs)} jobs to database")
        except Exception as e:
            logger.error(f"Failed to save job database: {e}")
    
    def update_job_database(self, current_sf_jobs: List[Dict]) -> List[Dict]:
        """Update the master database with job lifecycle tracking"""
        database = self.load_job_database()
        current_date = datetime.now()
        
        # Create lookup of current jobs by URL
        current_job_urls = {job['jobUrl'] for job in current_sf_jobs}
        
        # Create lookup of existing jobs in database
        db_jobs_by_url = {job['jobUrl']: job for job in database}
        
        new_jobs = []
        updated_database = []
        
        # Process current jobs from API
        for job in current_sf_jobs:
            job_url = job['jobUrl']
            
            if job_url in db_jobs_by_url:
                # Existing job - update it but clear old match analysis for re-analysis
                existing_job = db_jobs_by_url[job_url]
                
                existing_job.update(job)  # Update with latest data
                existing_job['status'] = 'ACTIVE'
                existing_job['last_seen'] = current_date.isoformat()
                
                # Remove old match analysis - will be re-analyzed with current profile
                if 'match_analysis' in existing_job:
                    del existing_job['match_analysis']
                
                # Calculate days since first listed
                first_seen = datetime.fromisoformat(existing_job['first_seen'])
                existing_job['days_since_listed'] = (current_date - first_seen).days
                
                updated_database.append(existing_job)
            else:
                # New job
                job['status'] = 'ACTIVE'
                job['first_seen'] = current_date.isoformat()
                job['last_seen'] = current_date.isoformat()
                job['days_since_listed'] = 0
                updated_database.append(job)
                new_jobs.append(job)
        
        # Process existing jobs that are no longer current (mark as CLOSED)
        for job in database:
            if job['jobUrl'] not in current_job_urls:
                if job['status'] == 'ACTIVE':
                    # Just became closed
                    job['status'] = 'CLOSED'
                    job['closed_date'] = current_date.isoformat()
                    logger.info(f"Job closed: {job['title']}")
                
                # Calculate days until deletion for closed jobs
                if job['status'] == 'CLOSED':
                    closed_date = datetime.fromisoformat(job['closed_date'])
                    days_closed = (current_date - closed_date).days
                    job['days_until_deletion'] = max(0, 5 - days_closed)
                    
                    # Only keep if within 5-day window
                    if days_closed < 5:
                        # Calculate days since first listed
                        first_seen = datetime.fromisoformat(job['first_seen'])
                        job['days_since_listed'] = (closed_date - first_seen).days
                        
                        # Remove old match analysis for closed jobs too (in case they reopen)
                        if 'match_analysis' in job:
                            del job['match_analysis']
                        
                        updated_database.append(job)
                    else:
                        logger.info(f"Job deleted: {job['title']} (closed for 5 days)")
        
        self.save_job_database(updated_database)
        return new_jobs

    def analyze_all_jobs(self, all_jobs: List[Dict]) -> List[Dict]:
        """Analyze ALL jobs (new and existing) for CV matching with current profile"""
        if not all_jobs:
            return []
        
        logger.info(f"Re-analyzing all {len(all_jobs)} jobs with current CV profile...")
        
        if self.config.get('enable_cv_matching', True):
            analyzed_jobs = self.job_matcher.batch_analyze_jobs(all_jobs)
            
            # Update database with fresh match analysis for all jobs
            database = self.load_job_database()
            for analyzed_job in analyzed_jobs:
                # Find and update the job in database
                for db_job in database:
                    if db_job['jobUrl'] == analyzed_job['jobUrl']:
                        db_job['match_analysis'] = analyzed_job['match_analysis']
                        break
            
            self.save_job_database(database)
            logger.info(f"Updated match analysis for all {len(analyzed_jobs)} jobs")
            return analyzed_jobs
        else:
            logger.info("CV matching disabled in config")
            return all_jobs

    def generate_dashboard_data(self):
        """Generate enhanced JSON data file for the web dashboard"""
        database = self.load_job_database()
        
        # Separate active and closed jobs for dashboard
        active_jobs = [job for job in database if job['status'] == 'ACTIVE']
        closed_jobs = [job for job in database if job['status'] == 'CLOSED']
        
        # Calculate match statistics
        match_stats = {
            'total_analyzed': len([j for j in active_jobs if j.get('match_analysis')]),
            'high_matches': len([j for j in active_jobs if j.get('match_analysis', {}).get('match_score', 0) >= 70]),
            'should_apply': len([j for j in active_jobs if j.get('match_analysis', {}).get('recommendation') == 'should_apply']),
            'average_score': 0
        }
        
        analyzed_jobs = [j for j in active_jobs if j.get('match_analysis')]
        if analyzed_jobs:
            scores = [j['match_analysis']['match_score'] for j in analyzed_jobs]
            match_stats['average_score'] = round(sum(scores) / len(scores), 1)
        
        dashboard_data = {
            'generated_at': datetime.now().isoformat(),
            'active_jobs': active_jobs,
            'closed_jobs': closed_jobs,
            'stats': {
                'total_active': len(active_jobs),
                'total_closed': len(closed_jobs),
                'departments': list(set(job.get('department', 'Unknown') for job in active_jobs)),
                'match_stats': match_stats
            }
        }
        
        # Save dashboard data
        dashboard_file = self.data_dir / "dashboard_data.json"
        try:
            with open(dashboard_file, 'w') as f:
                json.dump(dashboard_data, f, indent=2)
            logger.info(f"Dashboard data saved to {dashboard_file}")
        except Exception as e:
            logger.error(f"Failed to save dashboard data: {e}")
    
    def run_check(self):
        """Main method to run a job check with comprehensive CV matching"""
        logger.info("Starting OpenAI job check with comprehensive CV matching...")
        
        # Fetch current jobs
        all_jobs = self.fetch_jobs()
        if all_jobs is None:
            logger.error("Failed to fetch jobs, aborting check")
            return
        
        # Filter for San Francisco
        sf_jobs = self.filter_san_francisco_jobs(all_jobs)
        
        # Update database and identify new jobs
        new_jobs = self.update_job_database(sf_jobs)
        
        # Get all current jobs from database (both new and existing)
        database = self.load_job_database()
        all_current_jobs = [job for job in database if job['status'] == 'ACTIVE']
        
        # Re-analyze ALL current jobs with latest profile (ensures scores stay current)
        if self.config.get('reanalyze_all_jobs', True):
            logger.info(f"Re-analyzing all {len(all_current_jobs)} active jobs with current profile...")
            analyzed_all_jobs = self.analyze_all_jobs(all_current_jobs)
        else:
            # Only analyze new jobs
            logger.info(f"Analyzing only {len(new_jobs)} new jobs (reanalyze_all_jobs disabled)")
            analyzed_new_jobs = self.analyze_all_jobs(new_jobs) if new_jobs else []
            analyzed_all_jobs = all_current_jobs
        
        # Generate dashboard data export (includes all jobs with updated scores)
        self.generate_dashboard_data()
        
        logger.info(f"Job check completed - analyzed {len(analyzed_all_jobs)} total jobs, {len(new_jobs)} new jobs")
        
        # Log score statistics
        if analyzed_all_jobs:
            scores = [job.get('match_analysis', {}).get('match_score', 0) for job in analyzed_all_jobs]
            valid_scores = [s for s in scores if s > 0]
            if valid_scores:
                logger.info(f"Score range: {min(valid_scores)}-{max(valid_scores)}%, Average: {sum(valid_scores)/len(valid_scores):.1f}%")
                high_scores = len([s for s in valid_scores if s >= 70])
                logger.info(f"High scoring jobs (70%+): {high_scores}/{len(valid_scores)}")
            else:
                logger.warning("No valid match scores found - check CV matching configuration")

def load_config(config_file: str = "config.json") -> Dict:
    """Load configuration from JSON file"""
    default_config = {
        "email_enabled": False,
        "email_from": "",
        "email_to": "",
        "email_password": "",
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "check_time": "09:00",
        "first_run_days": 7,
        "include_remote": [],
        "attach_csv": True,
        "enable_cv_matching": True,
        "profile_path": "profile.json",
        "reanalyze_all_jobs": True
    }
    
    if Path(config_file).exists():
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
            default_config.update(user_config)
        except Exception as e:
            logger.warning(f"Could not load config file: {e}")
    
    return default_config

def main():
    parser = argparse.ArgumentParser(description='OpenAI Job Monitor with CV Matching')
    parser.add_argument('--run-once', action='store_true', help='Run once and exit')
    parser.add_argument('--create-config', action='store_true', help='Create sample config file')
    parser.add_argument('--config', default='config.json', help='Config file path')
    
    args = parser.parse_args()
    
    config = load_config(args.config)
    monitor = OpenAIJobMonitor(config)
    
    if args.run_once:
        monitor.run_check()
    else:
        monitor.start_scheduler()

if __name__ == "__main__":
    main()
