import React, { useState, useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { adminApi } from "../utils/adminApi";
import { formatFullDateTime } from "../utils/dateFormat";

interface DatabaseInfo {
  exists: boolean;
  size: number;
  size_mb: number;
  modified: string;
  table_count: number;
  user_count: number;
  store_count: number;
  rule_count: number;
  last_backup?: {
    timestamp: string;
    by: string;
  };
}

const AdminDatabase: React.FC = () => {
  const [dbInfo, setDbInfo] = useState<DatabaseInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [showConfirmRestore, setShowConfirmRestore] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    loadDatabaseInfo();
  }, []);

  const loadDatabaseInfo = async () => {
    try {
      setLoading(true);
      const info = await adminApi.getDatabaseInfo();
      setDbInfo(info);
    } catch (error) {
      console.error("Failed to load database info:", error);
      setError("Failed to load database information");
    } finally {
      setLoading(false);
    }
  };

  const handleBackup = async () => {
    try {
      setDownloading(true);
      setError("");
      await adminApi.backupDatabase();
      setSuccess("Database backup downloaded successfully");
      // Reload info to update last backup timestamp
      await loadDatabaseInfo();
    } catch (error: any) {
      setError(
        "Failed to download backup: " +
          (error.response?.data?.detail || "Unknown error"),
      );
    } finally {
      setDownloading(false);
    }
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (!file.name.endsWith(".sql") && !file.name.endsWith(".dump")) {
        setError("Please select a valid database backup file (.sql or .dump)");
        return;
      }
      setSelectedFile(file);
      setError("");
      setShowConfirmRestore(true);
    }
  };

  const handleRestore = async () => {
    if (!selectedFile || confirmText !== "RESTORE") {
      return;
    }

    try {
      setUploading(true);
      setError("");
      setUploadProgress(0);

      const result = await adminApi.restoreDatabase(
        selectedFile,
        (progress) => {
          setUploadProgress(progress);
        },
      );

      setSuccess(
        `Database restored successfully! ${result.details.users_restored} users, ${result.details.stores_restored} stores, and ${result.details.rules_restored} rules restored.`,
      );

      // Clear form
      setSelectedFile(null);
      setShowConfirmRestore(false);
      setConfirmText("");
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }

      // Redirect to login after 3 seconds
      setTimeout(() => {
        localStorage.removeItem("admin_token");
        navigate("/admin/login");
      }, 3000);
    } catch (error: any) {
      setError(
        "Failed to restore database: " +
          (error.response?.data?.detail || "Unknown error"),
      );
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && (file.name.endsWith(".sql") || file.name.endsWith(".dump"))) {
      setSelectedFile(file);
      setError("");
      setShowConfirmRestore(true);
    } else {
      setError("Please drop a valid database backup file (.sql or .dump)");
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const formatDate = (dateString: string) => {
    return formatFullDateTime(dateString, "UTC", "MMM d, yyyy HH:mm:ss");
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-lg">Loading database information...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                Database Management
              </h1>
              <p className="text-sm text-gray-600">
                Backup and restore system data
              </p>
            </div>
            <Link
              to="/admin/dashboard"
              className="bg-gray-100 hover:bg-gray-200 px-4 py-2 rounded text-sm"
            >
              ← Back to Dashboard
            </Link>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-6 sm:px-0">
          {/* Alerts */}
          {error && (
            <div className="mb-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          )}
          {success && (
            <div className="mb-4 bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded">
              {success}
            </div>
          )}

          {/* Database Info */}
          {dbInfo && (
            <div className="bg-white shadow rounded-lg mb-6">
              <div className="px-4 py-5 sm:p-6">
                <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">
                  Current Database Information
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Size</dt>
                    <dd className="text-lg font-medium text-gray-900">
                      {formatBytes(dbInfo.size)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Users</dt>
                    <dd className="text-lg font-medium text-gray-900">
                      {dbInfo.user_count}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-gray-500">
                      Stores
                    </dt>
                    <dd className="text-lg font-medium text-gray-900">
                      {dbInfo.store_count}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-gray-500">Rules</dt>
                    <dd className="text-lg font-medium text-gray-900">
                      {dbInfo.rule_count}
                    </dd>
                  </div>
                </div>
                {dbInfo.last_backup && (
                  <div className="mt-4 text-sm text-gray-600">
                    Last backup: {formatDate(dbInfo.last_backup.timestamp)} by{" "}
                    {dbInfo.last_backup.by}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Backup Section */}
          <div className="bg-white shadow rounded-lg mb-6">
            <div className="px-4 py-5 sm:p-6">
              <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">
                Backup Database
              </h3>
              <p className="text-sm text-gray-600 mb-4">
                Download a complete backup of the database including all users,
                stores, rules, and settings.
              </p>
              <button
                onClick={handleBackup}
                disabled={downloading}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {downloading ? "Downloading..." : "Download Backup"}
              </button>
            </div>
          </div>

          {/* Restore Section */}
          <div className="bg-white shadow rounded-lg">
            <div className="px-4 py-5 sm:p-6">
              <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">
                Restore Database
              </h3>
              <p className="text-sm text-gray-600 mb-4">
                Upload a previously downloaded backup to restore the system.
                This will replace all current data.
              </p>

              {/* File Upload Area */}
              <div
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-gray-400"
              >
                <svg
                  className="mx-auto h-12 w-12 text-gray-400"
                  stroke="currentColor"
                  fill="none"
                  viewBox="0 0 48 48"
                >
                  <path
                    d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8m-12 4h.02"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <p className="mt-2 text-sm text-gray-600">
                  Drop database file here or{" "}
                  <label className="text-blue-600 hover:text-blue-500 cursor-pointer">
                    browse
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".sql,.dump"
                      onChange={handleFileSelect}
                      className="hidden"
                    />
                  </label>
                </p>
                {selectedFile && (
                  <p className="mt-2 text-sm text-gray-900">
                    Selected: {selectedFile.name} (
                    {formatBytes(selectedFile.size)})
                  </p>
                )}
              </div>

              {/* Confirm Restore Dialog */}
              {showConfirmRestore && selectedFile && (
                <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <h4 className="text-sm font-medium text-yellow-800 mb-2">
                    ⚠️ Warning: This action will replace all current data
                  </h4>
                  <p className="text-sm text-yellow-700 mb-4">
                    You are about to restore from:{" "}
                    <strong>{selectedFile.name}</strong>
                  </p>
                  <p className="text-sm text-yellow-700 mb-4">
                    Type <strong>RESTORE</strong> to confirm:
                  </p>
                  <input
                    type="text"
                    value={confirmText}
                    onChange={(e) => setConfirmText(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md mb-4"
                    placeholder="Type RESTORE to confirm"
                  />
                  <div className="flex space-x-3">
                    <button
                      onClick={handleRestore}
                      disabled={confirmText !== "RESTORE" || uploading}
                      className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {uploading
                        ? `Uploading... ${uploadProgress}%`
                        : "Restore Database"}
                    </button>
                    <button
                      onClick={() => {
                        setShowConfirmRestore(false);
                        setSelectedFile(null);
                        setConfirmText("");
                        if (fileInputRef.current) {
                          fileInputRef.current.value = "";
                        }
                      }}
                      disabled={uploading}
                      className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

export default AdminDatabase;
