import { useEffect, useState } from 'react';
import { FileText, File as FileIcon, Check, RotateCcw, Loader2 } from 'lucide-react';

interface FileThumbnailProps {
  file: File;
  size?: 'sm' | 'md' | 'lg';
  uploadStatus?: 'pending' | 'uploading' | 'success' | 'error';
  uploadProgress?: number; // 0-100
  onRetry?: () => void;
}

export function FileThumbnail({ file, size = 'md', uploadStatus, uploadProgress = 0, onRetry }: FileThumbnailProps) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const isImage = file.type.startsWith('image/');

  useEffect(() => {
    if (isImage) {
      const url = URL.createObjectURL(file);
      setImageUrl(url);
      return () => URL.revokeObjectURL(url);
    }
  }, [file, isImage]);

  const sizeClasses = {
    sm: 'w-12 h-12',
    md: 'w-16 h-16',
    lg: 'w-24 h-24',
  };

  const iconSizeClasses = {
    sm: 'w-6 h-6',
    md: 'w-8 h-8',
    lg: 'w-12 h-12',
  };

  const borderClass = uploadStatus === 'error' ? 'border-red-500' : '';

  const renderStatusOverlay = () => {
    if (!uploadStatus) return null;

    switch (uploadStatus) {
      case 'pending':
        return (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 rounded-lg">
            <Loader2 className="w-4 h-4 text-white animate-spin" />
          </div>
        );
      case 'uploading':
        return (
          <div className="absolute bottom-0 left-0 right-0 h-1.5 bg-black/30 rounded-b-lg overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-200"
              style={{ width: `${Math.min(100, Math.max(0, uploadProgress))}%` }}
            />
          </div>
        );
      case 'success':
        return (
          <div className="absolute top-0.5 right-0.5 bg-green-500 rounded-full p-0.5">
            <Check className="w-2.5 h-2.5 text-white" />
          </div>
        );
      case 'error':
        return (
          <div className="absolute inset-0 flex items-center justify-center bg-red-500/30 rounded-lg">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRetry?.();
              }}
              className="bg-red-600 hover:bg-red-700 text-white rounded-full p-1 transition-colors"
              title="Retry upload"
            >
              <RotateCcw className="w-3 h-3" />
            </button>
          </div>
        );
      default:
        return null;
    }
  };

  if (isImage && imageUrl) {
    return (
      <div className={`${sizeClasses[size]} rounded-lg overflow-hidden border ${borderClass} bg-muted flex items-center justify-center relative`}>
        <img
          src={imageUrl}
          alt={file.name}
          className="w-full h-full object-cover"
        />
        {renderStatusOverlay()}
      </div>
    );
  }

  // Non-image file icons
  const getFileIcon = () => {
    if (file.type.includes('text')) {
      return <FileText className={iconSizeClasses[size]} />;
    }
    return <FileIcon className={iconSizeClasses[size]} />;
  };

  return (
    <div className={`${sizeClasses[size]} rounded-lg border ${borderClass} bg-muted flex items-center justify-center text-muted-foreground relative`}>
      {getFileIcon()}
      {renderStatusOverlay()}
    </div>
  );
}
