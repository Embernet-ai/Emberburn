# EmberBurn - Documentation Index

**Quick Reference for All EmberBurn Rancher App Store Documentation**

---

## 📚 Documentation Overview

This directory contains complete documentation for deploying, managing, and supporting EmberBurn in the Rancher App Store with multi-tenant capabilities.

---

## 🎯 Quick Start

**New to EmberBurn?** Start here:

1. **[DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)** - Read this first! Complete overview of what was done and deployment status
2. **[QUICKSTART.md](QUICKSTART.md)** - Fast deployment commands for quick testing

---

## 👥 For Clients (Subscribed Users)

### Primary Documentation
**[RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md)** - **START HERE**
- Complete guide for deploying EmberBurn via Rancher UI
- Multi-tenant deployment scenarios
- Step-by-step wizard walkthrough
- Resource preset explanations
- Service access instructions
- Configuration guide
- Troubleshooting
- FAQ
- RBAC and permissions explained
- Backup and recovery

### Quick Reference
**[README.md](README.md)**
- Chart overview
- Basic configuration
- Service descriptions
- Quick deployment examples

**[app-readme.md](app-readme.md)**
- What you see in Rancher App Catalog
- Feature highlights
- Multi-tenant benefits
- Quick deployment steps

### Multi-Architecture Support
**[../../docs/ARM64_DEPLOYMENT.md](../../docs/ARM64_DEPLOYMENT.md)**
- ARM64/aarch64 deployment guide
- Raspberry Pi deployment
- AWS Graviton deployment
- Apple Silicon support
- Performance comparisons
- Troubleshooting ARM64 issues

**[../../docs/MULTI_ARCH_QUICK_REFERENCE.md](../../docs/MULTI_ARCH_QUICK_REFERENCE.md)**
- Quick commands for multi-arch builds
- Platform-specific deployment
- Kubernetes node selectors
- Common use cases

---

## 🔧 For DevOps Team (Fireball Industries)

### Primary Documentation
**[PACKAGING_GUIDE.md](PACKAGING_GUIDE.md)** - **START HERE**
- Complete packaging procedures
- File structure breakdown
- Rancher annotation explanations
- RBAC configuration details
- PVC write permissions setup
- Testing procedures
- Version management
- Troubleshooting for DevOps
- Catalog integration steps

### Deployment Verification
**[DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)**
- Pre-deployment verification checklist
- File structure validation
- Configuration checks
- Security verification
- Testing procedures
- Sign-off requirements
- PowerShell validation commands

### Architecture Reference
**[MULTI_TENANT_NOTES.md](MULTI_TENANT_NOTES.md)**
- Multi-tenancy architecture
- Namespace isolation details
- Resource quota implementation
- Network policies
- RBAC design

---

## 📖 By Use Case

### "I want to deploy EmberBurn for my organization"
→ **[RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md)**

### "I need to package and publish EmberBurn to the app store"
→ **[PACKAGING_GUIDE.md](PACKAGING_GUIDE.md)** → **[DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)**

### "I want to understand the multi-tenant architecture"
→ **[DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)** → **[MULTI_TENANT_NOTES.md](MULTI_TENANT_NOTES.md)**

### "I need to troubleshoot a deployment issue"
→ **[RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md)** (Troubleshooting section) → **[PACKAGING_GUIDE.md](PACKAGING_GUIDE.md)** (Troubleshooting Rancher Issues)

### "I want a quick test deployment"
→ **[QUICKSTART.md](QUICKSTART.md)**

### "I need to verify everything is ready"
→ **[DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)**

---

## 📁 File Organization

### Helm Chart Files
```
Chart.yaml                  # Chart metadata with Rancher annotations
values.yaml                 # Default configuration values
questions.yaml              # Rancher UI form configuration
.helmignore                 # Files to exclude from packaging
```

### Documentation Files
```
README.md                   # General chart documentation
app-readme.md               # Rancher catalog tile description
RANCHER_APP_STORE_GUIDE.md  # Client deployment guide (comprehensive)
PACKAGING_GUIDE.md          # DevOps packaging procedures (internal)
DEPLOYMENT_CHECKLIST.md     # Pre-deployment verification
DEPLOYMENT_SUMMARY.md       # Complete overview and status
QUICKSTART.md               # Fast deployment reference
MULTI_TENANT_NOTES.md       # Multi-tenancy architecture
DOCUMENTATION_INDEX.md      # This file
```

### Template Files
```
templates/
  _helpers.tpl                   # Template helper functions
  NOTES.txt                      # Post-deployment instructions
  namespace.yaml                 # Namespace creation
  serviceaccount.yaml            # Service account
  role.yaml                      # RBAC role
  rolebinding.yaml               # RBAC binding
  deployment.yaml                # Main EmberBurn deployment
  configmap-tags.yaml            # Tag configuration
  configmap-publishers.yaml      # Publisher configuration
  pvc.yaml                       # Persistent storage
  service-opcua.yaml             # OPC UA service
  service-webui.yaml             # Web UI service
  service-prometheus.yaml        # Prometheus metrics service
  ingress.yaml                   # Optional ingress
  hpa.yaml                       # Horizontal pod autoscaler
  servicemonitor.yaml            # Prometheus ServiceMonitor
  networkpolicy.yaml             # Network policies
  pod-disruption-budget.yaml     # High availability
```

---

## 🔑 Key Concepts

### Multi-Tenancy
EmberBurn supports multiple isolated deployments in a single cluster:
- Each deployment gets its own namespace
- Separate RBAC per namespace
- Independent storage (PVCs)
- No port conflicts via LoadBalancer
- Resource quotas enforced per namespace

**Learn more**: [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "Multi-Tenant Deployment Scenarios"

### Self-Service Portal
Clients can deploy EmberBurn without IT assistance:
- Discover in Rancher Apps & Marketplace
- Configure via UI form (questions.yaml)
- One-click deployment
- Manage via Rancher UI
- Fleet available as fallback

**Learn more**: [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "For Clients: Deploying EmberBurn"

### RBAC & Permissions
Secure, namespace-scoped permissions:
- ServiceAccount auto-created
- Role with read access to namespace resources
- RoleBinding ties them together
- No cluster-wide permissions needed
- fsGroup 1000 for PVC write access

**Learn more**: [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) → "RBAC & Permissions"

### Write Permissions
PVC is fully writable by EmberBurn:
- `fsGroup: 1000` in pod security context
- Container runs as user/group 1000
- Mount path: `/app/data` with read/write
- Files: SQLite DB, logs, backups

**Learn more**: [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) → "PVC Write Permissions"

---

## 🚀 Deployment Workflow

### 1. Packaging (DevOps)
```
PACKAGING_GUIDE.md → DEPLOYMENT_CHECKLIST.md → helm package
```

### 2. Publishing (DevOps)
```
Copy to Helm-Charts repo → Generate index.yaml → Push to GitHub
```

### 3. Catalog Setup (DevOps)
```
Add repo to Rancher → Verify in catalog → Test deployment
```

### 4. Client Deployment (Self-Service)
```
Rancher UI → Apps & Marketplace → EmberBurn → Configure → Deploy
```

### 5. Client Access (Self-Service)
```
Service Discovery → External IP → Web UI at http://<ip>:5000
```

---

## 📊 Documentation Matrix

| Document | Audience | Purpose | When to Use |
|----------|----------|---------|-------------|
| **DEPLOYMENT_SUMMARY.md** | All | Complete overview | First read, status check |
| **RANCHER_APP_STORE_GUIDE.md** | Clients | Deployment guide | Deploying EmberBurn |
| **PACKAGING_GUIDE.md** | DevOps | Packaging procedures | Publishing to catalog |
| **DEPLOYMENT_CHECKLIST.md** | DevOps | Pre-deployment verification | Before packaging |
| **README.md** | All | Chart overview | Quick reference |
| **app-readme.md** | Clients | Catalog description | Appears in Rancher |
| **QUICKSTART.md** | All | Fast deployment | Quick testing |
| **MULTI_TENANT_NOTES.md** | DevOps/Architects | Architecture details | Understanding design |

---

## 🔍 Finding Information

### Configuration Questions

**Q: What resource presets are available?**
→ [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "Step 2: Configure Your Deployment" → "Resources"

**Q: How do I enable MQTT?**
→ [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "Step 2: Configure Your Deployment" → "Protocols"

**Q: What storage size should I use?**
→ [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "Cost Optimization" → "Storage Sizing"

### Troubleshooting Questions

**Q: Pod stuck in Pending?**
→ [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "Managing Your Deployment" → "Troubleshooting"

**Q: Can't access Web UI?**
→ [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "Step 4: Access EmberBurn"

**Q: Permission denied writing to PVC?**
→ [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) → "Troubleshooting Rancher App Store Issues" → "PVC Write Permission Denied"

### Architecture Questions

**Q: How does multi-tenancy work?**
→ [MULTI_TENANT_NOTES.md](MULTI_TENANT_NOTES.md) + [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md) → "Multi-Tenant Architecture"

**Q: What RBAC permissions are needed?**
→ [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md) → "Permissions Summary"

**Q: How are namespaces isolated?**
→ [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "Permissions & Security" → "Namespace Isolation"

### Deployment Questions

**Q: How do I package the chart?**
→ [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) → "Packaging for Rancher App Store"

**Q: How do I add to Rancher catalog?**
→ [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) → "Step 5: Add to Rancher Catalog"

**Q: How do I verify everything is ready?**
→ [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)

---

## 🆘 Support Resources

### For Clients
- **Documentation**: [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md)
- **FAQ**: [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "FAQ"
- **Troubleshooting**: [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) → "Troubleshooting"
- **Fleet Fallback**: Contact patrick@fireballz.ai

### For DevOps
- **Packaging**: [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md)
- **Testing**: [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) → "Testing Multi-Tenant Deployment"
- **Troubleshooting**: [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) → "Troubleshooting Rancher App Store Issues"

---

## 📝 Document Versions

All documentation is for:
- **EmberBurn Version**: 1.0.0
- **Chart Version**: 1.0.0
- **Rancher Version**: >= 2.6.0
- **Kubernetes Version**: >= 1.25.0
- **Last Updated**: 2026-01-13

---

## ✅ Verification Commands

### Check Documentation Completeness
```powershell
cd c:\Users\Admin\Documents\GitHub\Small-Application\helm\opcua-server

# List all documentation
Get-ChildItem -Filter "*.md" | Select-Object Name, Length, LastWriteTime

# Verify required docs exist
$docs = @(
  "README.md",
  "app-readme.md",
  "RANCHER_APP_STORE_GUIDE.md",
  "PACKAGING_GUIDE.md",
  "DEPLOYMENT_CHECKLIST.md",
  "DEPLOYMENT_SUMMARY.md",
  "DOCUMENTATION_INDEX.md"
)

foreach ($doc in $docs) {
  if (Test-Path $doc) {
    Write-Output "✓ $doc"
  } else {
    Write-Output "✗ MISSING: $doc"
  }
}
```

### Validate Chart
```powershell
# Lint chart
helm lint .

# Test template rendering
helm template emberburn . --debug

# Dry-run installation
helm install test . --namespace test --create-namespace --dry-run
```

---

## 🎓 Learning Path

### New to EmberBurn?
1. Read [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)
2. Review [app-readme.md](app-readme.md) for feature overview
3. Follow [QUICKSTART.md](QUICKSTART.md) for quick test

### Deploying for Clients?
1. Read [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) completely
2. Review [MULTI_TENANT_NOTES.md](MULTI_TENANT_NOTES.md) for architecture
3. Follow deployment wizard in Rancher UI

### DevOps/Publishing?
1. Read [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) completely
2. Follow [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
3. Test with [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) → "Testing Multi-Tenant Deployment"
4. Publish following [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) → "Packaging for Rancher App Store"

---

## 📞 Contact & Support

**Fireball Industries**
- Email: patrick@fireballz.ai
- Website: https://fireballz.ai/emberburn
- GitHub: https://github.com/fireball-industries

**For Clients**:
- Self-service via Rancher UI (primary)
- Documentation in [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md)
- Fleet deployment fallback (contact support)

**For DevOps**:
- Internal procedures in [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md)
- Architecture details in [MULTI_TENANT_NOTES.md](MULTI_TENANT_NOTES.md)

---

## 🔥 Quick Links

| What You Need | Document | Section |
|---------------|----------|---------|
| **Deploy EmberBurn** | [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) | For Clients: Deploying EmberBurn |
| **Multi-tenant setup** | [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) | Multi-Tenant Deployment Scenarios |
| **Package chart** | [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) | Packaging for Rancher App Store |
| **Verify deployment** | [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) | Pre-Deployment Tests |
| **Troubleshoot issues** | [RANCHER_APP_STORE_GUIDE.md](RANCHER_APP_STORE_GUIDE.md) | Troubleshooting |
| **RBAC permissions** | [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md) | Permissions Summary |
| **Write permissions** | [PACKAGING_GUIDE.md](PACKAGING_GUIDE.md) | RBAC & Permissions |
| **Architecture overview** | [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md) | Multi-Tenant Architecture |

---

**Where Data Meets Fire** 🔥

*EmberBurn v1.0.0 - Complete Documentation Set*  
*Fireball Industries*  
*Last Updated: 2026-01-13*
