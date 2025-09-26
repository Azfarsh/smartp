# SmartPrint Admin Dashboard

A professional admin dashboard for monitoring all SmartPrint business activities with Django admin authentication.

## Features

### 🔐 Authentication
- Django admin authentication system
- Staff member access control
- Secure session management

### 📊 Dashboard Categories
1. **User Data** - Monitor all users, their payments, and activity
2. **Vendor Data** - Track vendor performance, jobs, and earnings
3. **Vendor Transactions** - Financial transaction monitoring
4. **Contact Data** - Customer contact management
5. **New Vendor Installation** - Track vendor onboarding
6. **Total Activity** - System-wide activity monitoring

### 🎨 Professional UI
- Modern sidebar navigation
- Responsive design
- Real-time data loading
- Search functionality for each category
- Professional styling with gradients and animations

## Setup Instructions

### 1. Create Admin User
```bash
cd smartp-1/smartprint
python create_admin_user.py
```

### 2. Run the Server
```bash
python manage.py runserver
```

### 3. Access Admin Dashboard
Navigate to: `http://localhost:8000/admin-dashboard/`

## Usage

### Accessing the Dashboard
1. Make sure you're logged in as a staff user
2. Navigate to `/admin-dashboard/`
3. Use the sidebar to switch between categories

### User Data Management
- View all registered users
- See total payments per user
- Search users by name or email
- Monitor user activity and login status

### Vendor Data Management
- Track vendor performance metrics
- Monitor job completion rates
- View vendor earnings
- Search vendors by various criteria

### Search Functionality
- Each category has its own search bar
- Real-time filtering as you type
- Search across user names, emails, and other relevant fields

## Technical Details

### Files Created/Modified
- `templates/admin_dashboard.html` - Main dashboard template
- `print/admin_views.py` - Admin-specific views
- `print/urls.py` - Added admin dashboard URLs
- `create_admin_user.py` - Admin user creation script

### Authentication
- Uses Django's `@staff_member_required` decorator
- Requires `is_staff=True` for access
- Integrates with existing Django admin system

### Data Sources
- **Users**: Django User model
- **Payments**: R2 bucket metadata
- **Vendor Stats**: R2 bucket analysis
- **Other Data**: Placeholder for future implementation

### R2 Integration
- Direct connection to Cloudflare R2 storage
- Real-time data fetching
- Payment tracking from file metadata
- Vendor performance analysis

## Security Features

- Staff-only access
- CSRF protection
- Secure session management
- Input validation and sanitization

## Future Enhancements

- Real-time WebSocket updates
- Advanced analytics and charts
- Export functionality
- Email notifications
- Audit logging
- Role-based permissions

## Troubleshooting

### Can't Access Dashboard
1. Ensure you're logged in as a staff user
2. Check if `is_staff=True` in user profile
3. Verify URL is correct: `/admin-dashboard/`

### Data Not Loading
1. Check R2 credentials in settings
2. Verify database connection
3. Check browser console for errors

### Search Not Working
1. Ensure JavaScript is enabled
2. Check for console errors
3. Verify AJAX endpoints are accessible

## Support

For issues or questions about the admin dashboard, check:
1. Django logs for server errors
2. Browser console for client-side errors
3. R2 connection status
4. Database connectivity

---

**Note**: This admin dashboard is designed for internal use only and requires proper authentication. Make sure to keep admin credentials secure and limit access to authorized personnel only.
