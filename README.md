# Jenkins CLI

## Getting a Jenkins API Token

1. Log in to your Jenkins instance
2. Click on your username in the top right
3. Click on "Security" in the left sidebar
4. Click on "API Token" section
5. Click "Add new Token" and give it a name

## Installation

1. Get to the root directory of the project
   ```
   cd jenkins-cli
   ```

2. Install the package
   ```
   pip install -e .
   ```

3. Create a `.env` file in the root directory with your Jenkins credentials:
   ```
   JENKINS_URL=https://jenkins.your-org.com
   JENKINS_USER=your-username
   JENKINS_TOKEN=your-api-token
   
   # Available services (comma-separated list)
   AVAILABLE_SERVICES=service1,service2,service3
   ```

## Quick Reference

### Service Operations

| Operation | Command                           | Partial Names | Description                                                                 |
|-----------|-----------------------------------|---------------|-----------------------------------------------------------------------------|
| **Services** | `j services`                      | ✅ Yes | List all available servicesto scale up and deploy                           |
| **Branches** | `j branches`                      | ✅ Yes | List cached branch names                                                    |
| **Jobs** | `j jobs`                          | ✅ Yes | List all available Jenkins jobs in test-collateral (build/scale-up/deplpoy) |
| **Cache** | `j cache`                         | ✅ Yes | Manage job and branch caches                                                |
| **Scale** | `j scale <service>`               | ✅ Yes | Scale up a service (default TTL: 5h)                                        |
| **Build** | `j build <build-jobe-name>`       | ✅ Yes | Build a service (quality checks off by default)                             |
| **Deploy** | `j deploy <service> <build>`      | ✅ Yes | Deploy a specific build number                                              |
| **Status** | `j status <job-name>`             | ✅ Yes | Check job status                                                            |
| **Console** | `j console <job-name>`            | ✅ Yes | View console output of the jenkins jobclear                                 |
| **Job Params** | `j job-params <job partial name>` | ✅ Yes | Show last job run parameters                                                |

### Examples

```bash
# List all available services
j services

# Filter services by name (e.g., find all services with "api" in the name)
j services --filter api

# List services in table format
j services --format table

# List cached branch names
j branches

# Filter cached branches
j branches --filter feature

# List branches in table format
j branches --format table

# List all Jenkins jobs (uses cache)
j jobs

# Force refresh jobs from Jenkins
j jobs --refresh

# Show cache information
j cache --info

# Clear job cache
j cache --clear

# Clear branch cache
j cache --clear-branches

# Scale up a service (with smart matching)
j scale my-service

# Scale up with suggestions if no exact match found
j scale my-svc --suggest

# Build a service with quality checks
j build my-service -q -b <full-branch-name> --w

# Deploy build #123 of a service (with smart matching)
j deploy my-service 123 -w

# Deploy with suggestions if no exact match found
j deploy my-svc 123 --suggest

# Check status of a build job
j status my-service

# View console output
j console my-service

```

### Branch Name Caching

**Automatic Branch Caching:**
- Branch names are automatically cached when used with `j build` command
- `dev` branch is excluded from caching (by design)
- Most recently used branches appear first in suggestions
- Cache stores up to 50 branch names

**Branch Matching Priority:**
1. **Cached branches** (most recent first)
2. **Git branches** (fallback)

**Branch Caching Examples:**
```bash
# First time using a branch - gets cached
j build my-service -b feature-123-my-awesome-feature

# Later, you can use partial names and it will match from cache
j build my-service -b feature-123    # Matches feature-123-my-awesome-feature from cache
j build my-service -b feature        # Matches feature-123-my-awesome-feature from cache

# List cached branches
j branches
j branches --filter feature
```

## Usage

After installation, you can use the `j` command directly:

### List available services

List all available services:
```
j services
```

Filter services by name (partial match):
```
j services --filter api
j services -f service
```

List services in table format:
```
j services --format table
```

### List test-collateral jobs

List all jobs (fast mode is on by default):
```
j jobs
```

List only specific job types:
```
j jobs --type scale
j jobs --type build
j jobs --type deploy
```

Force refresh from Jenkins (ignore cache):
```
j jobs --refresh
```

### List cached branch names

List all cached branches:
```
j branches
```

Filter cached branches:
```
j branches --filter feature
```

List branches in table format:
```
j branches --format table
```

### Manage caches

Show cache information:
```
j cache --info
```

Clear the job cache:
```
j cache --clear
```

Clear the branch cache:
```
j cache --clear-branches
```

### Run scale up jobs

Scale up a service (uses test-collateral-Scale-up job):
```
j scale my-service
```

The CLI will automatically match partial names to the full service name.

Get service name suggestions if no exact match is found:
```
j scale my-svc --suggest
```

Specify time to live (default is 5 hours):
```
j scale my-service --ttl 8
```

Wait for the job to complete:
```
j scale my-service --wait
```

### Run build jobs

Build a service (with partial name matching):
```
j build my-service
```

Build with tests and code quality checks enabled:
```
j build my-service -q
```

Specify a different branch (default is 'dev'):
```
j build my-service -b feature-123-my-awesome-feature
```

Build with quality checks and a specific branch:
```
j build my-service -q -b feature-123-my-awesome-feature
```

Wait for the build to complete:
```
j build my-service --wait
```

Short form options:
```
j build my-service -q -b main -w
```

### Deploy builds

Deploy a specific build (with smart service name matching):
```
j deploy my-service 123
```

The CLI will automatically match partial names to the full service name.

Get service name suggestions if no exact match is found:
```
j deploy my-svc 123 --suggest
```

Wait for the deployment to complete:
```
j deploy my-service 123 --wait
```

### Check job status

Check the status of the latest build:
```
j status my-service
```

Check the status of a specific build:
```
j status my-service 123
```

Wait for a running job to complete:
```
j status my-service --wait
```

### View console output

View the console output of the latest build:
```
j console my-service
```

View the console output of a specific build:
```
j console my-service 123
```

View only the last part of the console output:
```
j console my-service --tail
```

Follow the console output in real-time:
```
j console my-service --follow
```

### Show job parameters

View the parameters available for a job:
```
j job-params my-service
```

## Requirements

- Python 3.6+
- Jenkins instance with API access