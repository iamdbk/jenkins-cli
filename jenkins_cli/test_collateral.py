#!/usr/bin/env python3
"""
Test Collateral Jobs CLI - A specialized tool for test-collateral Jenkins jobs
"""

import os
import sys
import click
import jenkins
import time
import re
import subprocess
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from tabulate import tabulate

# Load environment variables from .env file
load_dotenv()

# Jenkins connection settings
JENKINS_URL = os.getenv("JENKINS_URL")
JENKINS_USER = os.getenv("JENKINS_USER")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN")

# Base folder for all jobs
BASE_FOLDER = "test-collateral"

# Cache settings
CACHE_DURATION_MINUTES = 1440  # Cache jobs for 24 hours (1440 minutes)
CACHE_FILE = os.path.expanduser("~/.jenkins_cli_cache.json")
BRANCH_CACHE_FILE = os.path.expanduser("~/.jenkins_cli_branch_cache.json")

# Available services list - loaded from environment variable only
services_env = os.getenv("AVAILABLE_SERVICES")
if services_env:
    AVAILABLE_SERVICES = [s.strip() for s in services_env.split(",") if s.strip()]
else:
    AVAILABLE_SERVICES = []

def get_jenkins_client():
    """Create and return a Jenkins client instance"""
    if not all([JENKINS_URL, JENKINS_USER, JENKINS_TOKEN]):
        click.echo("Error: Jenkins connection details not found.")
        click.echo("Please create a .env file with JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN.")
        click.echo("Example:")
        click.echo("JENKINS_URL=https://jenkins.your-org.com")
        click.echo("JENKINS_USER=your-username")
        click.echo("JENKINS_TOKEN=your-api-token")
        sys.exit(1)
    
    try:
        server = jenkins.Jenkins(JENKINS_URL, username=JENKINS_USER, password=JENKINS_TOKEN)
        # Test connection
        server.get_whoami()
        return server
    except jenkins.JenkinsException as e:
        click.echo(f"Error connecting to Jenkins: {e}")
        click.echo("Please check your credentials and Jenkins URL.")
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error connecting to Jenkins: {e}")
        sys.exit(1)

def load_jobs_cache():
    """Load jobs from cache file if valid"""
    try:
        if not os.path.exists(CACHE_FILE):
            return None
        
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        
        # Check if cache is still valid
        cache_time = datetime.fromisoformat(cache_data['timestamp'])
        if datetime.now() - cache_time > timedelta(minutes=CACHE_DURATION_MINUTES):
            return None
        
        return cache_data['jobs']
    except (json.JSONDecodeError, KeyError, ValueError):
        return None

def save_jobs_cache(jobs):
    """Save jobs to cache file"""
    try:
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'jobs': jobs
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
    except Exception:
        # Ignore cache save errors
        pass

def get_jobs(force_refresh=False):
    """Get jobs from cache or Jenkins API"""
    if not force_refresh:
        cached_jobs = load_jobs_cache()
        if cached_jobs is not None:
            return cached_jobs
    
    # Fetch from Jenkins API
    server = get_jenkins_client()
    try:
        folder_info = server.get_job_info(BASE_FOLDER)
        if not folder_info:
            click.echo(f"Error: Folder '{BASE_FOLDER}' not found.")
            return []
        
        jobs = folder_info.get('jobs', [])
        save_jobs_cache(jobs)
        return jobs
    except Exception as e:
        click.echo(f"Error fetching jobs from Jenkins: {e}")
        return []

def load_branch_cache():
    """Load branch names from cache file"""
    try:
        if not os.path.exists(BRANCH_CACHE_FILE):
            return []
        
        with open(BRANCH_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        
        return cache_data.get('branches', [])
    except (json.JSONDecodeError, KeyError, ValueError):
        return []

def save_branch_cache(branches):
    """Save branch names to cache file"""
    try:
        cache_data = {
            'branches': branches
        }
        with open(BRANCH_CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
    except Exception:
        # Ignore cache save errors
        pass

def add_branch_to_cache(branch_name):
    """Add a branch name to the cache (excluding 'dev')"""
    if branch_name.lower() == 'dev':
        return
    
    cached_branches = load_branch_cache()
    
    # Remove the branch if it already exists (to move it to the front)
    if branch_name in cached_branches:
        cached_branches.remove(branch_name)
    
    # Add to the beginning of the list (most recent first)
    cached_branches.insert(0, branch_name)
    
    # Keep only the last 50 branches to prevent cache from growing too large
    cached_branches = cached_branches[:50]
    
    save_branch_cache(cached_branches)

def get_cached_branches():
    """Get cached branch names for autocompletion"""
    return load_branch_cache()

def is_folder(job_info):
    """Check if a job is actually a folder"""
    return job_info.get('_class', '').endswith('Folder')

def get_job_path(job_name):
    """Get the full path to a job in the test-collateral folder"""
    return f"{BASE_FOLDER}/{job_name}"

def job_exists(server, job_name):
    """Check if a job exists in the test-collateral folder"""
    job_path = get_job_path(job_name)
    return server.job_exists(job_path)

def get_job_info(server, job_name):
    """Get info for a job in the test-collateral folder"""
    job_path = get_job_path(job_name)
    return server.get_job_info(job_path)

def wait_for_build_to_finish(server, job_name, build_number, timeout=300, poll_interval=5):
    """Wait for a build to finish and return the result"""
    job_path = get_job_path(job_name)
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            build_info = server.get_build_info(job_path, build_number)
            if not build_info.get('building'):
                return build_info.get('result')
            click.echo(f"Build #{build_number} is still running... (elapsed: {int(time.time() - start_time)}s)")
            time.sleep(poll_interval)
        except Exception as e:
            click.echo(f"Error checking build status: {e}")
            time.sleep(poll_interval)
    
    click.echo(f"Timeout reached ({timeout}s). Build is still running.")
    return "TIMEOUT"

def find_matching_service(partial_name, available_services):
    """Find a service name that matches the partial name provided"""
    if not partial_name or not available_services:
        return None
    
    # Case 1: Exact match
    for service in available_services:
        if service.lower() == partial_name.lower():
            return service
    
    # Case 2: Service contains the partial name
    matches = []
    for service in available_services:
        if partial_name.lower() in service.lower():
            matches.append(service)
    
    # If we found exactly one match, return it
    if len(matches) == 1:
        return matches[0]
    
    # If we found multiple matches, return the one that starts with the partial name
    for match in matches:
        if match.lower().startswith(partial_name.lower()):
            return match
    
    # If we still have multiple matches, return the shortest one
    if matches:
        return min(matches, key=len)
    
    # No match found
    return None

def get_service_suggestions(partial_name, max_suggestions=10):
    """Get service name suggestions based on partial input"""
    if not partial_name:
        return AVAILABLE_SERVICES[:max_suggestions]
    
    partial_lower = partial_name.lower()
    matches = []
    
    # First, find exact matches
    for service in AVAILABLE_SERVICES:
        if service.lower() == partial_lower:
            matches.append(service)
    
    # Then, find services that start with the partial name
    for service in AVAILABLE_SERVICES:
        if service.lower().startswith(partial_lower) and service not in matches:
            matches.append(service)
    
    # Finally, find services that contain the partial name
    for service in AVAILABLE_SERVICES:
        if partial_lower in service.lower() and service not in matches:
            matches.append(service)
    
    return matches[:max_suggestions]

def get_available_services(server, job_info):
    """Get available services from job parameters"""
    valid_services = []
    try:
        # Try to extract available services from job parameters
        for prop in job_info.get('property', []):
            if prop.get('_class', '').endswith('ParametersDefinitionProperty'):
                for param_def in prop.get('parameterDefinitions', []):
                    if param_def.get('name') == 'SERVICES':
                        choices = param_def.get('choices', [])
                        if choices:
                            valid_services = [choice.strip() for choice in choices]
                        break
    except Exception:
        # If we can't get the valid services, return empty list
        pass
    return valid_services

def get_available_branches(service_name=None):
    """Get available git branches for a service
    
    This function attempts to get branch information using git commands.
    If git is not available or we're not in a git repository, it returns
    a default list of common branches.
    """
    # Default common branches to return if git command fails
    default_branches = ['dev', 'main', 'master', 'develop', 'release']
    
    try:
        # Try to get branches from git
        cmd = ['git', 'branch', '-a']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        
        if result.returncode == 0:
            # Parse the output to get branch names
            branches = []
            for line in result.stdout.splitlines():
                # Clean up the branch name
                branch = line.strip()
                if branch.startswith('*'):
                    branch = branch[1:].strip()  # Remove the asterisk for current branch
                if branch.startswith('remotes/origin/'):
                    branch = branch[len('remotes/origin/'):].strip()
                if branch and branch not in branches and not branch.endswith('/HEAD'):
                    branches.append(branch)
            
            # If we found branches, return them
            if branches:
                return branches
    except (subprocess.SubprocessError, FileNotFoundError, TimeoutError):
        # If git command fails, fall back to default branches
        pass
    
    # Return default branches if git command failed or returned no branches
    return default_branches

def find_matching_branch(partial_name):
    """Find a branch that matches the partial name provided"""
    # First check cached branches (most recent first)
    cached_branches = get_cached_branches()
    
    if not partial_name:
        return 'dev'  # Default branch
    
    # Case 1: Exact match in cached branches
    for branch in cached_branches:
        if branch.lower() == partial_name.lower():
            return branch
    
    # Case 2: Cached branch contains the partial name
    matches = []
    for branch in cached_branches:
        if partial_name.lower() in branch.lower():
            matches.append(branch)
    
    # If we found exactly one match in cache, return it
    if len(matches) == 1:
        return matches[0]
    
    # If we found multiple matches in cache, return the one that starts with the partial name
    for match in matches:
        if match.lower().startswith(partial_name.lower()):
            return match
    
    # If we still have multiple matches in cache, return the first one (most recent)
    if matches:
        return matches[0]
    
    # Fall back to git branches if no cache matches
    available_branches = get_available_branches()
    
    # Case 3: Exact match in git branches
    for branch in available_branches:
        if branch.lower() == partial_name.lower():
            return branch
    
    # Case 4: Git branch contains the partial name
    matches = []
    for branch in available_branches:
        if partial_name.lower() in branch.lower():
            matches.append(branch)
    
    # If we found exactly one match in git, return it
    if len(matches) == 1:
        return matches[0]
    
    # If we found multiple matches in git, return the one that starts with the partial name
    for match in matches:
        if match.lower().startswith(partial_name.lower()):
            return match
    
    # If we still have multiple matches in git, return the shortest one
    if matches:
        return min(matches, key=len)
    
    # No match found, return the partial name as is
    return partial_name

@click.group()
def cli():
    """Test Collateral Jobs CLI - Run and manage test-collateral Jenkins jobs"""
    pass

@cli.command()
@click.option('--all', '-a', is_flag=True, help='Show all jobs including folders')
@click.option('--type', '-t', type=click.Choice(['scale', 'build', 'deploy']), help='Filter jobs by type')
@click.option('--fast', '-f', is_flag=True, help='Fast mode (skip detailed status)', default=True)
@click.option('--refresh', '-r', is_flag=True, help='Force refresh from Jenkins (ignore cache)')
def jobs(all, type, fast, refresh):
    """List jobs in the test-collateral folder"""
    
    try:
        # Get jobs from cache or Jenkins API
        jobs = get_jobs(force_refresh=refresh)
        if not jobs:
            click.echo(f"No jobs found in {BASE_FOLDER} folder.")
            return
        
        # Filter jobs by type first to reduce processing
        filtered_jobs = []
        for job in jobs:
            name = job['name']
            
            # Filter by job type if specified
            if type:
                if type == 'scale' and 'scale' not in name.lower():
                    continue
                if type == 'build' and 'build' not in name.lower():
                    continue
                if type == 'deploy' and 'deploy' not in name.lower():
                    continue
            
            filtered_jobs.append(job)
        
        if not filtered_jobs:
            click.echo(f"No jobs found matching type '{type}'.")
            return
        
        job_data = []
        
        # Fast mode - just show job names and basic info
        if fast:
            for job in filtered_jobs:
                name = job['name']
                color = job.get('color', 'unknown')
                
                # Check if it's a folder (without fetching details)
                if name.endswith('/') or color == 'nobuilt':
                    if all:  # Only show folders if --all is specified
                        job_data.append([name, "Folder"])
                    continue
                
                # Basic status from color
                status_map = {
                    'blue': 'Success',
                    'green': 'Success',
                    'red': 'Failed',
                    'yellow': 'Unstable',
                    'grey': 'Not Built',
                    'disabled': 'Disabled',
                    'aborted': 'Aborted',
                    'notbuilt': 'Not Built'
                }
                
                # Handle colors with _anime suffix (running jobs)
                if color and '_anime' in color:
                    status = f"{status_map.get(color.replace('_anime', ''), 'Unknown')} (Running)"
                else:
                    status = status_map.get(color, 'Unknown')
                
                job_data.append([name, status])
        else:
            # Detailed mode - get full status for each job
            for job in filtered_jobs:
                name = job['name']
                job_path = get_job_path(name)
                
                # Try to get more detailed job info
                try:
                    job_info = server.get_job_info(job_path)
                    is_job_folder = is_folder(job_info)
                    
                    # Skip folders if not showing all
                    if is_job_folder and not all:
                        continue
                    
                    # Get job status
                    if is_job_folder:
                        status = "Folder"
                    else:
                        # Get last build info if available
                        if job_info.get('lastBuild'):
                            last_build = job_info['lastBuild']
                            build_number = last_build.get('number', 'N/A')
                            
                            # Try to get build status
                            try:
                                build_info = server.get_build_info(job_path, build_number)
                                if build_info.get('building'):
                                    status = "Building"
                                else:
                                    status = build_info.get('result', 'Unknown')
                            except:
                                status = "Unknown"
                        else:
                            status = "Not Built"
                    
                    job_data.append([name, status])
                except Exception as e:
                    job_data.append([name, "Error"])
        
        click.echo(tabulate(job_data, headers=["Job Name", "Status"], tablefmt="grid"))
    
    except Exception as e:
        click.echo(f"Error listing jobs: {e}")

@cli.command()
@click.option('--filter', '-f', help='Filter services by name (partial match)')
@click.option('--format', type=click.Choice(['list', 'table']), default='list', help='Output format')
def services(filter, format):
    """List all available services for scaling"""
    filtered_services = AVAILABLE_SERVICES
    
    if filter:
        filter_lower = filter.lower()
        filtered_services = [service for service in AVAILABLE_SERVICES if filter_lower in service.lower()]
    
    if not filtered_services:
        click.echo(f"No services found matching '{filter}'")
        return
    
    if format == 'table':
        # Create table data
        table_data = []
        for i, service in enumerate(filtered_services, 1):
            table_data.append([i, service])
        
        click.echo(tabulate(table_data, headers=["#", "Service Name"], tablefmt="grid"))
    else:
        # Simple list format
        click.echo("Available services:")
        for service in filtered_services:
            click.echo(f"  {service}")
    
    click.echo(f"\nTotal: {len(filtered_services)} services")
    click.echo("Usage: j scale <service-name>")

@cli.command()
@click.option('--filter', '-f', help='Filter branches by name')
@click.option('--format', type=click.Choice(['list', 'table']), default='list', help='Output format')
def branches(filter, format):
    """List cached branch names for autocompletion"""
    cached_branches = get_cached_branches()
    
    if not cached_branches:
        click.echo("No branches cached yet.")
        click.echo("Branches are automatically cached when you use them with 'j build' command.")
        return
    
    # Filter branches if specified
    filtered_branches = cached_branches
    if filter:
        filter_lower = filter.lower()
        filtered_branches = [branch for branch in cached_branches if filter_lower in branch.lower()]
    
    if not filtered_branches:
        click.echo(f"No cached branches match '{filter}'.")
        return
    
    if format == 'table':
        # Table format
        headers = ['#', 'Branch Name']
        table_data = []
        for i, branch in enumerate(filtered_branches, 1):
            table_data.append([i, branch])
        
        click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))
    else:
        # Simple list format
        click.echo("Cached branches:")
        for i, branch in enumerate(filtered_branches, 1):
            click.echo(f"  {i}. {branch}")
    
    click.echo(f"\nTotal: {len(filtered_branches)} branches")
    click.echo("Usage: j build <service> -b <branch-name>")
    click.echo("Note: 'dev' branch is not cached (excluded by design)")

@cli.command()
@click.option('--clear', '-c', is_flag=True, help='Clear the job cache')
@click.option('--clear-branches', is_flag=True, help='Clear the branch cache')
@click.option('--info', '-i', is_flag=True, help='Show cache information')
def cache(clear, clear_branches, info):
    """Manage job and branch caches"""
    if clear:
        try:
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
                click.echo("Job cache cleared successfully.")
            else:
                click.echo("No job cache file found.")
        except Exception as e:
            click.echo(f"Error clearing job cache: {e}")
    
    elif clear_branches:
        try:
            if os.path.exists(BRANCH_CACHE_FILE):
                os.remove(BRANCH_CACHE_FILE)
                click.echo("Branch cache cleared successfully.")
            else:
                click.echo("No branch cache file found.")
        except Exception as e:
            click.echo(f"Error clearing branch cache: {e}")
    
    elif info:
        try:
            # Job cache info
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'r') as f:
                    cache_data = json.load(f)
                
                cache_time = datetime.fromisoformat(cache_data['timestamp'])
                age = datetime.now() - cache_time
                jobs_count = len(cache_data.get('jobs', []))
                
                click.echo("=== Job Cache ===")
                click.echo(f"Cache file: {CACHE_FILE}")
                click.echo(f"Created: {cache_time.strftime('%Y-%m-%d %H:%M:%S')}")
                click.echo(f"Age: {age}")
                click.echo(f"Jobs cached: {jobs_count}")
                cache_hours = CACHE_DURATION_MINUTES // 60
                click.echo(f"Cache duration: {cache_hours} hours")
                
                if age > timedelta(minutes=CACHE_DURATION_MINUTES):
                    click.echo("Status: EXPIRED")
                else:
                    remaining = timedelta(minutes=CACHE_DURATION_MINUTES) - age
                    remaining_hours = int(remaining.total_seconds() // 3600)
                    remaining_minutes = int((remaining.total_seconds() % 3600) // 60)
                    if remaining_hours > 0:
                        click.echo(f"Status: VALID (expires in {remaining_hours}h {remaining_minutes}m)")
                    else:
                        click.echo(f"Status: VALID (expires in {remaining_minutes}m)")
            else:
                click.echo("=== Job Cache ===")
                click.echo("No job cache file found.")
            
            # Branch cache info
            click.echo("\n=== Branch Cache ===")
            if os.path.exists(BRANCH_CACHE_FILE):
                with open(BRANCH_CACHE_FILE, 'r') as f:
                    branch_cache_data = json.load(f)
                
                branches = branch_cache_data.get('branches', [])
                click.echo(f"Cache file: {BRANCH_CACHE_FILE}")
                click.echo(f"Branches cached: {len(branches)}")
                
                if branches:
                    click.echo("Recent branches:")
                    for i, branch in enumerate(branches[:10], 1):
                        click.echo(f"  {i}. {branch}")
                    if len(branches) > 10:
                        click.echo(f"  ... and {len(branches) - 10} more")
                else:
                    click.echo("No branches cached yet.")
            else:
                click.echo("No branch cache file found.")
                
        except Exception as e:
            click.echo(f"Error reading cache info: {e}")
    
    else:
        click.echo("Cache management commands:")
        click.echo("  j cache --clear         Clear the job cache")
        click.echo("  j cache --clear-branches Clear the branch cache")
        click.echo("  j cache --info          Show cache information")

@cli.command()
@click.argument('partial_service_name')
@click.option('--ttl', '-t', type=int, default=5, help='Time to live in hours (default: 5)')
@click.option('--wait', '-w', is_flag=True, help='Wait for job to complete')
def scale(partial_service_name, ttl, wait):
    """Run a scale up job for a service (partial name match)"""
    server = get_jenkins_client()
    
    try:
        # Use the fixed job name for scale-up
        scale_job_name = "test-collateral-Scale-up"
        job_path = get_job_path(scale_job_name)
        
        if not server.job_exists(job_path):
            click.echo(f"Error: Scale job '{scale_job_name}' not found.")
            return
        
        # Get job info to check parameters
        job_info = server.get_job_info(job_path)
        
        # Find the best matching service name
        matched_service = find_matching_service(partial_service_name, AVAILABLE_SERVICES)
        
        if not matched_service:
            click.echo(f"Error: No service found matching '{partial_service_name}'")
            
            # Always show suggestions for better user experience
            suggestions = get_service_suggestions(partial_service_name)
            if suggestions:
                click.echo("\nDid you mean one of these?")
                for i, suggestion in enumerate(suggestions, 1):
                    click.echo(f"  {i}. {suggestion}")
                click.echo(f"\nUse: j scale <service-name>")
                click.echo("Tip: You can use partial names like 'eur' for 'euronext-collateral-service'")
            else:
                click.echo("No similar services found.")
            
            click.echo("\nUse 'j services' to see all available services.")
            click.echo("Use 'j services --filter <partial-name>' to filter services.")
            return
        
        # Use the matched service name
        service_name = matched_service
        
        # If the matched service is different from input, inform the user
        if matched_service != partial_service_name:
            click.echo(f"Matched '{partial_service_name}' to '{matched_service}'")
        
        # Set up parameters
        parameters = {
            'SERVICES': service_name,
            'TIME_TO_LIVE': str(ttl)
        }
        
        # Run the scale up job
        queue_id = server.build_job(job_path, parameters=parameters)
        click.echo(f"Scale up job for '{service_name}' triggered successfully.")
        click.echo(f"Queue ID: {queue_id}")
        click.echo(f"Time to live: {ttl} hours")
        
        if wait:
            click.echo("Waiting for job to complete...")
            # Wait for job to start
            time.sleep(5)
            
            # Get build number
            job_info = server.get_job_info(job_path)
            if job_info.get('lastBuild'):
                build_number = job_info['lastBuild'].get('number')
                if build_number:
                    result = wait_for_build_to_finish(server, scale_job_name, build_number)
                    click.echo(f"Job completed with result: {result}")
    
    except Exception as e:
        click.echo(f"Error running scale up job: {e}")

@cli.command()
@click.argument('partial_service_name')
@click.option('--quality', '-q', is_flag=True, help='Enable both tests and code quality checks')
@click.option('--branch', '-b', default='dev', help='Branch to build (partial name match, default: dev)')
@click.option('--wait', '-w', is_flag=True, help='Wait for job to complete')
@click.option('--debug', '-d', is_flag=True, help='Show debug information')
def build(partial_service_name, quality, branch, wait, debug):
    """Run a build job for a service (partial name match) - quality checks disabled by default"""
    server = get_jenkins_client()
    
    try:
        # Get jobs from cache or Jenkins API
        jobs = get_jobs()
        
        # Find all build jobs
        build_jobs = []
        for job in jobs:
            if 'build' in job['name'].lower() and not job['name'].lower().endswith('-report'):
                build_jobs.append(job)
        
        if not build_jobs:
            click.echo("No build jobs found.")
            return
            
        # Use the input job name as-is (no cleaning)
        search_name = partial_service_name.lower()
            
        # Find matching job
        matching_jobs = []
        for job in build_jobs:
            job_name = job['name'].lower()
                
            if search_name in job_name:
                matching_jobs.append(job)
                
        # If no exact match but we have partial matches
        if not matching_jobs:
            click.echo(f"Error: No build job matching '{partial_service_name}' found.")
            click.echo("Available build jobs:")
            for job in build_jobs:
                job_name = job['name']
                click.echo(f"  - {job_name}")
            return
            
        # Debug: Show all matching jobs
        if debug and len(matching_jobs) > 1:
            click.echo(f"Debug: Found {len(matching_jobs)} matching jobs:")
            for job in matching_jobs:
                click.echo(f"Debug:   - {job['name']}")
        
        # If we have multiple matches, find the best one
        if len(matching_jobs) > 1:
            # First, check for exact matches
            exact_matches = []
            for job in matching_jobs:
                job_name = job['name'].lower()
                if job_name == search_name:
                    exact_matches.append(job)
                    
            if exact_matches:
                matching_jobs = exact_matches
                if debug:
                    click.echo(f"Debug: Using exact match")
            else:
                # Check for jobs that start with "test-collateral-{search_name}"
                # This gives priority to jobs like "test-collateral-collateral-api-build"
                prefix_matches = []
                for job in matching_jobs:
                    job_name = job['name'].lower()
                    if job_name.startswith(f"test-collateral-{search_name}"):
                        prefix_matches.append(job)
                        
                if prefix_matches:
                    matching_jobs = prefix_matches
                    if debug:
                        click.echo(f"Debug: Using prefix match with 'test-collateral-{search_name}'")
                else:
                    # Fallback: Check for jobs that start with the partial name
                    start_matches = []
                    for job in matching_jobs:
                        job_name = job['name'].lower()
                        if job_name.startswith(search_name):
                            start_matches.append(job)
                            
                    if start_matches:
                        matching_jobs = start_matches
                        if debug:
                            click.echo(f"Debug: Using start match with '{search_name}'")
                    
        # Use the first (or only) matching job
        selected_job = matching_jobs[0]
        build_job_name = selected_job['name']
        job_path = get_job_path(build_job_name)
        
        if debug:
            click.echo(f"Debug: Selected job: {build_job_name}")
        
        # Extract service name from job name by matching against AVAILABLE_SERVICES
        # Job name format: test-collateral-{service}-build
        # We need to extract just the {service} part for SERVICENAME parameter
        service_name = build_job_name
        
        # Try to match a service from AVAILABLE_SERVICES in the job name
        # Sort by length (longest first) to match the most specific service name
        matched_services = []
        for available_service in AVAILABLE_SERVICES:
            # Check if this service appears in the job name
            # For example: "test-collateral-eurex-build" contains "eurex"
            if available_service in build_job_name:
                matched_services.append(available_service)
        
        # Use the longest matching service name (most specific)
        if matched_services:
            service_name = max(matched_services, key=len)
        # If no match found in AVAILABLE_SERVICES, fallback to string replacement
        elif build_job_name.startswith('test-collateral-'):
            service_name = build_job_name.replace('test-collateral-', '').replace('-build', '')
        
        # Set up parameters based on the Jenkins UI
        parameters = {
            'SERVICENAME': service_name,
        }
        
        # For quality parameters, use the correct values based on job-params output
        # Jenkins expects 'Yes'/'No' for PT_SINGLE_SELECT parameters
        # Quality is disabled by default, but can be enabled with --quality or -q
        if quality:
            # Enable quality checks
            parameters['EnableTests'] = 'Yes'
            parameters['EnableCodequality'] = 'Yes'
        else:
            # Disable quality checks (default behavior)
            parameters['EnableTests'] = 'No'
            parameters['EnableCodequality'] = 'No'
        
        # Find matching branch and cache it
        matched_branch = find_matching_branch(branch)
        
        # Cache the branch name (excluding 'dev')
        add_branch_to_cache(matched_branch)
        
        # Try with origin/ prefix for the branch name
        # This is a common format expected by Jenkins
        original_branch = matched_branch  # Use the matched branch name
        
        # Add origin/ prefix if it's not already there
        if not original_branch.startswith('origin/'):
            prefixed_branch = f"origin/{original_branch}"
        else:
            prefixed_branch = original_branch
            
        # Add the branch parameter with the origin/ prefix
        parameters['GIT_REVISION'] = prefixed_branch
        
        # Print debug info about parameters
        if debug:
            click.echo(f"Debug: Original branch '{branch}' matched to '{matched_branch}'")
            click.echo(f"Debug: Sending parameters to Jenkins:")
            for key, value in parameters.items():
                click.echo(f"Debug:   {key}: {value}")
        
        # Run the build job
        try:
            # Use direct requests to the Jenkins API
            jenkins_url = os.getenv("JENKINS_URL")
            jenkins_user = os.getenv("JENKINS_USER")
            jenkins_token = os.getenv("JENKINS_TOKEN")
            
            # Construct the URL for the build with parameters
            build_url = f"{jenkins_url}/job/{job_path.replace('/', '/job/')}/buildWithParameters"
            
            # Set up authentication
            auth = (jenkins_user, jenkins_token)
            
            if debug:
                click.echo(f"Debug: Preparing request to {build_url}")
            
            # Build the URL manually to avoid URL encoding of forward slashes in branch name
            url_params = []
            for key, value in parameters.items():
                # Don't encode the forward slash in GIT_REVISION parameter
                if key == 'GIT_REVISION':
                    # Replace spaces with %20 but leave forward slashes as-is
                    encoded_value = value.replace(' ', '%20')
                else:
                    encoded_value = requests.utils.quote(value)
                url_params.append(f"{key}={encoded_value}")
            
            # Construct the final URL
            full_url = f"{build_url}?{'&'.join(url_params)}"
            
            # Send the request without parameters (they're already in the URL)
            response = requests.post(full_url, auth=auth)
            
            # Print the actual URL that was sent
            if debug:
                click.echo(f"DEBUG: Constructed URL: {full_url}")
                click.echo(f"DEBUG: Actual request URL: {response.request.url}")
                click.echo(f"DEBUG: Request body: {response.request.body}")
            
            # Check if the request was successful
            # Jenkins might return 201 Created or 302 Found for successful build triggers
            if response.status_code in [201, 302]:
                # Extract the queue ID from the Location header
                location = response.headers.get('Location')
                if location:
                    queue_id = location.split('/')[-1]
                else:
                    queue_id = "unknown"
                
                if debug:
                    click.echo(f"Debug: Request successful with status code {response.status_code}")
                    click.echo(f"Debug: Response headers: {dict(response.headers)}")
            else:
                if debug:
                    click.echo(f"Debug: Request failed with status code {response.status_code}")
                    click.echo(f"Debug: Response: {response.text}")
                    click.echo(f"Debug: Response headers: {dict(response.headers)}")
                    click.echo(f"Debug: URL: {build_url}")
                    click.echo(f"Debug: Parameters: {parameters}")
                # Provide more helpful error message for common issues
                error_msg = f"Failed to trigger build: {response.status_code} {response.reason}"
                if response.status_code == 400:
                    error_msg += "\nPossible causes: Invalid branch name, invalid parameters, or branch not found."
                    error_msg += "\nCheck if the branch exists in your repository."
                
                raise Exception(error_msg)
        except Exception as e:
            if debug:
                click.echo(f"Debug: Error with direct request: {e}")
            
            # Fall back to using the python-jenkins library
            try:
                queue_id = server.build_job(job_path, parameters=parameters)
            except Exception as e2:
                if debug:
                    click.echo(f"Debug: Error with python-jenkins: {e2}")
                raise e
        
        # Get build number - simple approach: add 1 to the last build number
        build_number = None
        
        try:
            # Wait a moment for the build to be queued
            time.sleep(2)
            
            # Get the last build number and add 1
            job_info = server.get_job_info(job_path)
            if job_info.get('lastBuild'):
                last_build_number = job_info['lastBuild'].get('number')
                if last_build_number:
                    build_number = last_build_number + 1
        except Exception:
            # If we can't get the build number, we'll show "pending"
            pass
        
        # Print clean output
        click.echo(f"Build job '{build_job_name}' triggered successfully.")
        if build_number:
            click.echo(f"Build #{build_number}")
        else:
            click.echo("Build #pending")
        click.echo(f"Branch: {prefixed_branch}")
        click.echo(f"Quality: {'Enabled' if quality else 'Disabled'}")
        
        if wait:
            click.echo("Waiting for job to complete...")
            # Wait for job to start
            time.sleep(5)
            
            # Use the build number we already calculated
            if build_number:
                result = wait_for_build_to_finish(server, build_job_name, build_number)
                click.echo(f"Job completed with result: {result}")
                
                if result == "SUCCESS":
                    click.echo(f"Build #{build_number} completed successfully.")
                    click.echo(f"You can deploy this build with: j deploy {service_name} {build_number}")
            else:
                click.echo("Could not determine build number to wait for.")
    
    except Exception as e:
        click.echo(f"Error running build job: {e}")
        import traceback
        click.echo(traceback.format_exc())

@cli.command()
@click.argument('partial_service_name')
def job_params(partial_service_name):
    """Show Jenkins job parameters for a service"""
    server = get_jenkins_client()
    
    try:
        # Get jobs from cache or Jenkins API
        jobs = get_jobs()
        
        # Find all build jobs
        build_jobs = []
        for job in jobs:
            if 'build' in job['name'].lower() and not job['name'].lower().endswith('-report'):
                build_jobs.append(job)
        
        if not build_jobs:
            click.echo("No build jobs found.")
            return
            
        # Use the input job name as-is (no cleaning)
        search_name = partial_service_name.lower()
            
        # Find matching job
        matching_jobs = []
        for job in build_jobs:
            job_name = job['name'].lower()
                
            if search_name in job_name:
                matching_jobs.append(job)
                
        if not matching_jobs:
            click.echo(f"Error: No build job matching '{partial_service_name}' found.")
            click.echo("Available build jobs:")
            for job in build_jobs:
                job_name = job['name']
                click.echo(f"  - {job_name}")
            return
            
        # Use the first matching job
        selected_job = matching_jobs[0]
        build_job_name = selected_job['name']
        job_path = get_job_path(build_job_name)
        
        # Get job info
        job_info = server.get_job_info(job_path)
        
        click.echo(f"Job: {build_job_name}")
        click.echo(f"Path: {job_path}")
        click.echo("Parameters:")
        
        # Extract parameters
        if job_info.get('property'):
            for prop in job_info.get('property', []):
                if prop.get('_class', '').endswith('ParametersDefinitionProperty'):
                    for param_def in prop.get('parameterDefinitions', []):
                        param_name = param_def.get('name')
                        param_type = param_def.get('type', 'Unknown')
                        param_default = param_def.get('defaultParameterValue', {}).get('value', 'None')
                        param_description = param_def.get('description', 'No description')
                        
                        click.echo(f"  - {param_name} ({param_type})")
                        click.echo(f"    Default: {param_default}")
                        click.echo(f"    Description: {param_description}")
                        
                        # Show choices for choice parameters
                        if param_def.get('choices'):
                            choices = param_def.get('choices', [])
                            click.echo(f"    Choices: {', '.join(choices)}")
                        click.echo()
        else:
            click.echo("  No parameters defined for this job.")
    
    except Exception as e:
        click.echo(f"Error getting job parameters: {e}")


@cli.command()
@click.argument('partial_service_name')
@click.argument('build_number')
@click.option('--wait', '-w', is_flag=True, help='Wait for job to complete')
def deploy(partial_service_name, build_number, wait):
    """Deploy a specific build of a service (partial name match)"""
    server = get_jenkins_client()
    
    try:
        # Use the fixed deploy job name
        deploy_job_name = "test-collateral-Deploy-services"
        job_path = get_job_path(deploy_job_name)
        
        if not server.job_exists(job_path):
            click.echo(f"Error: Deploy job '{deploy_job_name}' not found.")
            return
        
        # Find the best matching service name
        matched_service = find_matching_service(partial_service_name, AVAILABLE_SERVICES)
        
        if not matched_service:
            click.echo(f"Error: No service found matching '{partial_service_name}'")
            
            # Always show suggestions for better user experience
            suggestions = get_service_suggestions(partial_service_name)
            if suggestions:
                click.echo("\nDid you mean one of these?")
                for i, suggestion in enumerate(suggestions, 1):
                    click.echo(f"  {i}. {suggestion}")
                click.echo(f"\nUse: j deploy <service-name> <build-number>")
                click.echo("Tip: You can use partial names like 'eur' for 'euronext-collateral-service'")
            else:
                click.echo("No similar services found.")
            
            click.echo("\nUse 'j services' to see all available services.")
            click.echo("Use 'j services --filter <partial-name>' to filter services.")
            return
        
        # Use the matched service name
        service_name = matched_service
        
        # If the matched service is different from input, inform the user
        if matched_service != partial_service_name:
            click.echo(f"Matched '{partial_service_name}' to '{matched_service}'")
        
        # Set up parameters
        parameters = {
            'SERVICENAME': service_name,
            'BUILD_NO': build_number
        }
        
        # Run the deploy job
        queue_id = server.build_job(job_path, parameters=parameters)
        click.echo(f"Deploy job for '{service_name}' build #{build_number} triggered successfully.")
        click.echo(f"Queue ID: {queue_id}")
        
        if wait:
            click.echo("Waiting for job to complete...")
            # Wait for job to start
            time.sleep(5)
            
            # Get build number
            job_info = server.get_job_info(job_path)
            if job_info.get('lastBuild'):
                job_build_number = job_info['lastBuild'].get('number')
                if job_build_number:
                    result = wait_for_build_to_finish(server, deploy_job_name, job_build_number)
                    click.echo(f"Job completed with result: {result}")
    
    except Exception as e:
        click.echo(f"Error running deploy job: {e}")
        if wait:  # Only show traceback in debug mode
            import traceback
            click.echo(traceback.format_exc())

@cli.command()
@click.argument('partial_service_name')
@click.argument('build_number', required=False)
@click.option('--wait', '-w', is_flag=True, help='Wait for job to complete if still running')
def status(partial_service_name, build_number, wait):
    """Check the status of a job (partial name match)"""
    server = get_jenkins_client()
    
    try:
        # Get jobs from cache or Jenkins API
        jobs = get_jobs()
        
        # Use the input job name as-is (no cleaning)
        search_name = partial_service_name.lower()
            
        # Find matching jobs
        matching_jobs = []
        for job in jobs:
            job_name = job['name'].lower()
                
            if search_name in job_name:
                matching_jobs.append(job)
                
        if not matching_jobs:
            click.echo(f"Error: No job matching '{partial_service_name}' found.")
            click.echo("Available jobs:")
            for job in jobs:
                job_name = job['name']
                click.echo(f"  - {job_name}")
            return
            
        # If we have multiple matches, find the best one
        if len(matching_jobs) > 1:
            # First, check for exact matches
            exact_matches = []
            for job in matching_jobs:
                job_name = job['name'].lower()
                if job_name == search_name:
                    exact_matches.append(job)
                    
            if exact_matches:
                matching_jobs = exact_matches
            else:
                # Check for jobs that start with the partial name
                start_matches = []
                for job in matching_jobs:
                    job_name = job['name'].lower()
                    if job_name.startswith(search_name):
                        start_matches.append(job)
                        
                if start_matches:
                    matching_jobs = start_matches
                    
        # Use the first (or only) matching job
        selected_job = matching_jobs[0]
        job_name = selected_job['name']
        job_path = get_job_path(job_name)
        
        # Use the full job name for display
        service_name = job_name
        
        # If we had multiple matches, inform the user which one we're using
        if len(matching_jobs) > 1:
            click.echo(f"Multiple matches found for '{partial_service_name}'. Using: {service_name}")
        
        if not server.job_exists(job_path):
            click.echo(f"Error: Job '{job_name}' not found in {BASE_FOLDER} folder.")
            return
        
        job_info = server.get_job_info(job_path)
        
        if is_folder(job_info):
            click.echo(f"Error: '{job_name}' is a folder, not a job.")
            return
        
        if not job_info.get('builds'):
            click.echo(f"Job '{job_name}' has no builds yet.")
            return
        
        # If build number not provided, use the latest build
        if not build_number:
            last_build = job_info.get('lastBuild', {})
            if not last_build:
                click.echo(f"Job '{job_name}' has no builds yet.")
                return
                
            build_number = last_build.get('number')
            if not build_number:
                click.echo(f"Job '{job_name}' has no build number available.")
                return
        
        # Get build info
        build_info = server.get_build_info(job_path, int(build_number))
        
        # Format timestamp
        from datetime import datetime
        timestamp = build_info.get('timestamp', 0)
        build_time = datetime.fromtimestamp(timestamp/1000).strftime('%Y-%m-%d %H:%M:%S')
        
        # Display build information
        click.echo(f"Job: {job_name}")
        click.echo(f"Build: #{build_number}")
        
        is_building = build_info.get('building', False)
        result = build_info.get('result') if not is_building else "BUILDING"
        
        click.echo(f"Status: {result}")
        click.echo(f"Started: {build_time}")
        
        if is_building:
            elapsed = (datetime.now().timestamp() * 1000 - timestamp) / 1000
            click.echo(f"Running for: {elapsed:.2f} seconds")
        else:
            click.echo(f"Duration: {build_info.get('duration', 0)/1000:.2f} seconds")
        
        click.echo(f"URL: {build_info.get('url', 'N/A')}")
        
        # Show parameters if any
        actions = build_info.get('actions', [])
        for action in actions:
            if action.get('_class', '').endswith('ParametersAction'):
                parameters = action.get('parameters', [])
                if parameters:
                    click.echo("\nParameters:")
                    for param in parameters:
                        name = param.get('name', 'Unknown')
                        value = param.get('value', 'N/A')
                        click.echo(f"  {name}: {value}")
        
        # Wait for build to finish if requested and still running
        if wait and is_building:
            click.echo("\nWaiting for job to complete...")
            result = wait_for_build_to_finish(server, job_name, int(build_number))
            click.echo(f"Job completed with result: {result}")
    
    except Exception as e:
        click.echo(f"Error checking job status: {e}")

@cli.command()
@click.argument('partial_service_name')
@click.argument('build_number', required=False)
@click.option('--tail', '-t', is_flag=True, help='Show only the last part of the console output')
@click.option('--lines', '-n', type=int, default=50, help='Number of lines to show when using --tail')
@click.option('--follow', '-f', is_flag=True, help='Follow the console output until job completes')
def console(partial_service_name, build_number, tail, lines, follow):
    """View console output for a job build (partial name match)"""
    server = get_jenkins_client()
    
    try:
        # Get jobs from cache or Jenkins API
        jobs = get_jobs()
        
        # Use the input job name as-is (no cleaning)
        search_name = partial_service_name.lower()
            
        # Find matching jobs
        matching_jobs = []
        for job in jobs:
            job_name = job['name'].lower()
                
            if search_name in job_name:
                matching_jobs.append(job)
                
        if not matching_jobs:
            click.echo(f"Error: No job matching '{partial_service_name}' found.")
            click.echo("Available jobs:")
            for job in jobs:
                job_name = job['name']
                click.echo(f"  - {job_name}")
            return
            
        # If we have multiple matches, find the best one
        if len(matching_jobs) > 1:
            # First, check for exact matches
            exact_matches = []
            for job in matching_jobs:
                job_name = job['name'].lower()
                if job_name == search_name:
                    exact_matches.append(job)
                    
            if exact_matches:
                matching_jobs = exact_matches
            else:
                # Check for jobs that start with the partial name
                start_matches = []
                for job in matching_jobs:
                    job_name = job['name'].lower()
                    if job_name.startswith(search_name):
                        start_matches.append(job)
                        
                if start_matches:
                    matching_jobs = start_matches
                    
        # Use the first (or only) matching job
        selected_job = matching_jobs[0]
        job_name = selected_job['name']
        job_path = get_job_path(job_name)
        
        # Use the full job name for display
        service_name = job_name
        
        # If we had multiple matches, inform the user which one we're using
        if len(matching_jobs) > 1:
            click.echo(f"Multiple matches found for '{partial_service_name}'. Using: {service_name}")
        
        if not server.job_exists(job_path):
            click.echo(f"Error: Job '{job_name}' not found in {BASE_FOLDER} folder.")
            return
        
        job_info = server.get_job_info(job_path)
        
        if is_folder(job_info):
            click.echo(f"Error: '{job_name}' is a folder, not a job.")
            return
        
        # If build number not provided, use the latest build
        if not build_number:
            if not job_info.get('builds'):
                click.echo(f"Job '{job_name}' has no builds yet.")
                return
                
            if not job_info.get('lastBuild'):
                click.echo(f"Job '{job_name}' has no last build information.")
                return
                
            build_number = job_info['lastBuild'].get('number')
            if not build_number:
                click.echo(f"Job '{job_name}' has no build number available.")
                return
        else:
            build_number = int(build_number)
        
        # Get initial console output
        console_output = server.get_build_console_output(job_path, build_number)
        
        if follow:
            # Get build info to check if it's still running
            build_info = server.get_build_info(job_path, build_number)
            is_building = build_info.get('building', False)
            
            # Show initial output
            if tail and console_output:
                console_lines = console_output.splitlines()
                if len(console_lines) > lines:
                    console_output = "\n".join(console_lines[-lines:])
            
            click.echo(f"Console output for {job_name} #{build_number}:")
            click.echo("=" * 80)
            click.echo(console_output)
            
            # If the job is still running, follow the output
            last_size = len(console_output)
            while is_building:
                time.sleep(2)
                
                # Get updated console output
                new_output = server.get_build_console_output(job_path, build_number)
                
                # If there's new content, print it
                if len(new_output) > last_size:
                    click.echo(new_output[last_size:], nl=False)
                    last_size = len(new_output)
                
                # Check if job is still running
                build_info = server.get_build_info(job_path, build_number)
                is_building = build_info.get('building', False)
            
            # Show final status
            result = build_info.get('result', 'UNKNOWN')
            click.echo(f"\nJob completed with result: {result}")
        else:
            # Just show the console output once
            if tail and console_output:
                console_lines = console_output.splitlines()
                if len(console_lines) > lines:
                    console_output = "\n".join(console_lines[-lines:])
                    click.echo(f"Console output for {job_name} #{build_number} (last {lines} lines):")
                else:
                    click.echo(f"Console output for {job_name} #{build_number}:")
            else:
                click.echo(f"Console output for {job_name} #{build_number}:")
                
            click.echo("=" * 80)
            click.echo(console_output)
    
    except Exception as e:
        click.echo(f"Error retrieving console output: {e}")

def main():
    cli()

if __name__ == "__main__":
    main()
