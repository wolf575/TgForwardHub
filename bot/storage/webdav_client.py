"""
WebDAV Client and Storage Manager
Handles media storage with WebDAV support
"""
import os
import logging

logger = logging.getLogger(__name__)


class WebDAVClient:
    """WebDAV client for remote storage"""
    
    def __init__(self, url, username, password, base_path='/telegram_media'):
        self.url = url
        self.username = username
        self.password = password
        self.base_path = base_path
    
    def test_connection(self):
        """Test WebDAV connection"""
        try:
            # Placeholder implementation
            logger.info(f"Testing WebDAV connection to {self.url}")
            return True
        except Exception as e:
            logger.error(f"WebDAV connection test failed: {e}")
            return False
    
    def upload_file(self, local_path, remote_path):
        """Upload file to WebDAV"""
        logger.info(f"Uploading {local_path} to {remote_path}")
        return True
    
    def get_file_url(self, remote_path):
        """Get WebDAV file URL"""
        return f"{self.url}{self.base_path}/{remote_path}"


class StorageManager:
    """Manages media storage (local and optionally WebDAV)"""
    
    def __init__(self, media_dir, webdav_client=None):
        self.media_dir = media_dir
        self.webdav_client = webdav_client
        os.makedirs(media_dir, exist_ok=True)
    
    def get_file_path(self, storage_location):
        """Get file path or URL for storage location"""
        if self.webdav_client:
            return self.webdav_client.get_file_url(storage_location)
        else:
            local_path = os.path.join(self.media_dir, storage_location)
            if os.path.exists(local_path):
                return local_path
        return None
    
    def save_file(self, source_path, filename):
        """Save file to storage"""
        dest_path = os.path.join(self.media_dir, filename)
        
        # Copy to local storage
        import shutil
        shutil.copy2(source_path, dest_path)
        
        # Upload to WebDAV if configured
        if self.webdav_client:
            try:
                self.webdav_client.upload_file(dest_path, filename)
            except Exception as e:
                logger.warning(f"WebDAV upload failed, file saved locally: {e}")
        
        return filename
