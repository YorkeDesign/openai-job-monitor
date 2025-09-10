#!/usr/bin/env python3
"""
Debug version of OpenAI Job Monitor to troubleshoot CV matching
"""

import json
import logging
from pathlib import Path
from job_matcher import JobMatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def debug_cv_matching():
    """Debug the CV matching functionality"""
    
    print("🔍 DEBUG: Testing CV Matching System")
    print("=" * 50)
    
    # 1. Check if profile.json exists and is valid
    profile_path = Path("profile.json")
    if not profile_path.exists():
        print("❌ ERROR: profile.json not found!")
        print("   Create profile.json with your CV data")
        return False
    
    try:
        with open(profile_path) as f:
            profile = json.load(f)
        print(f"✅ Profile loaded: {profile.get('personal_info', {}).get('name', 'Unknown')}")
        print(f"   Experience: {profile.get('personal_info', {}).get('years_experience', 0)} years")
        print(f"   Preferred roles: {len(profile.get('personal_info', {}).get('preferred_roles', []))}")
    except Exception as e:
        print(f"❌ ERROR loading profile: {e}")
        return False
    
    # 2. Test job matcher initialization
    try:
        matcher = JobMatcher()
        print("✅ JobMatcher initialized successfully")
        print(f"   API Key available: {'Yes' if matcher.api_key else 'No'}")
    except Exception as e:
        print(f"❌ ERROR initializing JobMatcher: {e}")
        return False
    
    # 3. Test with sample job data
    sample_job = {
        "title": "Director of Applied AI",
        "department": "Research",
        "team": "Applied AI",
        "descriptionPlain": "Lead strategic AI initiatives and guide product development. Work with cross-functional teams to identify opportunities for AI integration. Develop AI strategy and roadmaps. Lead technical teams without hands-on coding.",
        "location": "San Francisco, CA",
        "employmentType": "Full-time",
        "isRemote": False,
        "jobUrl": "https://example.com/job/1",
        "applyUrl": "https://example.com/apply/1"
    }
    
    print("\n🧪 Testing with sample job:")
    print(f"   Title: {sample_job['title']}")
    print(f"   Department: {sample_job['department']}")
    
    try:
        match_result = matcher.analyze_job_match(sample_job)
        print("\n✅ CV Matching successful!")
        print(f"   Match Score: {match_result['match_score']}%")
        print(f"   Recommendation: {match_result['recommendation']}")
        print(f"   Analysis: {match_result['analysis'][:100]}...")
        print(f"   Strong Matches: {match_result['strong_matches'][:3]}")
        
        if match_result['match_score'] == 0:
            print("⚠️  Warning: Match score is 0 - check profile skills matching")
            
    except Exception as e:
        print(f"❌ ERROR in CV matching: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 4. Check existing job database
    data_dir = Path("job_data")
    dashboard_file = data_dir / "dashboard_data.json"
    
    if dashboard_file.exists():
        try:
            with open(dashboard_file) as f:
                dashboard_data = json.load(f)
            
            active_jobs = dashboard_data.get('active_jobs', [])
            jobs_with_analysis = [j for j in active_jobs if 'match_analysis' in j]
            
            print(f"\n📊 Dashboard Data Status:")
            print(f"   Total active jobs: {len(active_jobs)}")
            print(f"   Jobs with match analysis: {len(jobs_with_analysis)}")
            
            if jobs_with_analysis:
                scores = [j['match_analysis']['match_score'] for j in jobs_with_analysis]
                print(f"   Score range: {min(scores)} - {max(scores)}%")
                print(f"   Average score: {sum(scores)/len(scores):.1f}%")
            else:
                print("   ⚠️  No jobs have match analysis data!")
                print("   This is why dashboard shows 'N/A'")
                
        except Exception as e:
            print(f"❌ ERROR reading dashboard data: {e}")
    else:
        print("\n📊 No dashboard data found - run job monitor first")
    
    print("\n🔧 Recommendations:")
    if not jobs_with_analysis:
        print("   1. Run: python openai_job_monitor.py --run-once")
        print("   2. Check that enable_cv_matching: true in config.json")
        print("   3. Ensure job_matcher.py is in the same directory")
    
    return True

def test_existing_jobs():
    """Test CV matching on existing jobs in database"""
    
    data_dir = Path("job_data")
    dashboard_file = data_dir / "dashboard_data.json"
    
    if not dashboard_file.exists():
        print("❌ No dashboard data found. Run the job monitor first.")
        return
    
    try:
        with open(dashboard_file) as f:
            dashboard_data = json.load(f)
        
        active_jobs = dashboard_data.get('active_jobs', [])
        if not active_jobs:
            print("❌ No active jobs found in database.")
            return
        
        print(f"\n🔄 Testing CV matching on {len(active_jobs)} existing jobs...")
        
        matcher = JobMatcher()
        analyzed_jobs = matcher.batch_analyze_jobs(active_jobs[:3])  # Test first 3
        
        print("\n📊 Results:")
        for job in analyzed_jobs:
            analysis = job.get('match_analysis', {})
            print(f"   {job['title']}: {analysis.get('match_score', 0)}% ({analysis.get('recommendation', 'N/A')})")
        
        # Update dashboard with analysis
        for job in active_jobs:
            job_url = job['jobUrl']
            for analyzed_job in analyzed_jobs:
                if analyzed_job['jobUrl'] == job_url:
                    job['match_analysis'] = analyzed_job['match_analysis']
                    break
        
        # Save updated data
        dashboard_data['active_jobs'] = active_jobs
        with open(dashboard_file, 'w') as f:
            json.dump(dashboard_data, f, indent=2)
        
        print("✅ Updated dashboard data with match analysis")
        print("   Refresh your dashboard to see scores!")
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--test-existing":
        test_existing_jobs()
    else:
        success = debug_cv_matching()
        if success:
            print("\n✅ CV matching system appears to be working!")
            print("\nTo test on existing jobs, run:")
            print("   python debug_job_monitor.py --test-existing")
        else:
            print("\n❌ CV matching system needs attention!")
