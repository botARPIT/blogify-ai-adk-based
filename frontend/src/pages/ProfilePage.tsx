import React, { useEffect, useState } from 'react';
import { getMe, type AuthUser } from '../lib/api/auth';
import { toast } from 'sonner';
import LoadingState from '../components/state/LoadingState';

const ProfilePage: React.FC = () => {
  const [profile, setProfile] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchProfile = async () => {
    setLoading(true);
    try {
      const response = await getMe();
      if (response.authenticated && response.user) {
        setProfile(response.user);
      } else {
        toast.error('Unable to load profile data.');
      }
    } catch (error) {
      console.error('Failed to fetch profile', error);
      toast.error('Failed to fetch profile');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProfile();
  }, []);

  if (loading) {
    return <LoadingState title="Loading Profile..." message="Fetching your data." />;
  }

  return (
    <div className="animate-in page-shell" style={{ maxWidth: '720px', margin: '0 auto' }}>
      <div className="page-header mb-md">
        <div className="page-header-copy">
          <span className="eyebrow-label">User Settings</span>
          <h1 className="page-title">Your Profile</h1>
        </div>
        <button className="brutalist-button secondary" onClick={fetchProfile}>
          Refresh
        </button>
      </div>

      {profile ? (
        <section className="bento-card panel-card" style={{ borderLeft: '4px solid var(--accent-color)' }}>
          <h2 className="card-title mb-md">Account Details</h2>
          
          <div className="detail-grid">
            <div className="meta-row" style={{ flexDirection: 'column', alignItems: 'flex-start', borderBottom: 'none' }}>
              <span className="eyebrow-label text-secondary">User ID</span>
              <span className="meta-value" style={{ fontSize: '1.25rem' }}>{profile.id}</span>
            </div>
            
            <div className="meta-row" style={{ flexDirection: 'column', alignItems: 'flex-start', borderBottom: 'none' }}>
              <span className="eyebrow-label text-secondary">Email</span>
              <span className="meta-value" style={{ fontSize: '1.25rem' }}>{profile.email}</span>
            </div>

            <div className="meta-row" style={{ flexDirection: 'column', alignItems: 'flex-start', borderBottom: 'none' }}>
              <span className="eyebrow-label text-secondary">Display Name</span>
              <span className="meta-value" style={{ fontSize: '1.25rem' }}>
                {profile.display_name || <span className="italic text-secondary">Not provided</span>}
              </span>
            </div>
          </div>
        </section>
      ) : (
        <div className="bento-card panel-card text-center">
          <p className="text-secondary">Could not load profile data.</p>
        </div>
      )}
    </div>
  );
};

export default ProfilePage;
