"use client";

import React, { useCallback, useEffect, useState } from "react";
import { apiClient, APIError, ModelMetadata } from "@/lib/api";
import { ErrorState } from "./ErrorState";
import { LoadingSkeleton } from "./LoadingSkeleton";

type PanelState =
  | { status: "loading" }
  | { status: "success"; data: ModelMetadata }
  | { status: "no_model" }
  | { status: "error" };

/**
 * Displays model performance metrics: training_date, MAE, RMSE, model_version.
 * Shows loading indicator while fetching, "no model trained" message on 404,
 * and error state with retry on fetch failure. Supports manual refresh.
 *
 * Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
 */
export function ModelInfoPanel() {
  const [state, setState] = useState<PanelState>({ status: "loading" });
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchMetadata = useCallback(async () => {
    try {
      const data = await apiClient.getModelMetadata();
      setState({ status: "success", data });
    } catch (error) {
      if (error instanceof APIError && error.status === 404) {
        setState({ status: "no_model" });
      } else {
        setState({ status: "error" });
      }
    }
  }, []);

  useEffect(() => {
    fetchMetadata();
  }, [fetchMetadata]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await fetchMetadata();
    setIsRefreshing(false);
  };

  if (state.status === "loading") {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Model Information</h2>
        </div>
        <LoadingSkeleton lines={4} />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Model Information</h2>
        </div>
        <ErrorState
          message="Model information could not be loaded."
          onRetry={handleRefresh}
        />
      </div>
    );
  }

  if (state.status === "no_model") {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Model Information</h2>
          <RefreshButton onClick={handleRefresh} isRefreshing={isRefreshing} />
        </div>
        <p className="text-sm text-gray-500">No model has been trained yet.</p>
      </div>
    );
  }

  const { data } = state;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Model Information</h2>
        <RefreshButton onClick={handleRefresh} isRefreshing={isRefreshing} />
      </div>
      <dl className="grid grid-cols-2 gap-4">
        <div>
          <dt className="text-xs font-medium text-gray-500">Training Date</dt>
          <dd className="mt-1 text-sm text-gray-900">
            {formatDate(data.training_date)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">Model Version</dt>
          <dd className="mt-1 text-sm text-gray-900">{data.model_version}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">MAE</dt>
          <dd className="mt-1 text-sm text-gray-900">
            {data.mean_absolute_error.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-gray-500">RMSE</dt>
          <dd className="mt-1 text-sm text-gray-900">
            {data.root_mean_squared_error.toFixed(2)}
          </dd>
        </div>
      </dl>
    </div>
  );
}

// --- Internal Components ---

interface RefreshButtonProps {
  onClick: () => void;
  isRefreshing: boolean;
}

function RefreshButton({ onClick, isRefreshing }: RefreshButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isRefreshing}
      className="rounded-md p-1.5 text-gray-400 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
      aria-label="Refresh model information"
    >
      <svg
        className={`h-5 w-5 ${isRefreshing ? "animate-spin" : ""}`}
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
        />
      </svg>
    </button>
  );
}

// --- Utilities ---

function formatDate(isoDate: string): string {
  try {
    const date = new Date(isoDate);
    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return isoDate;
  }
}
