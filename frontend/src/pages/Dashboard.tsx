import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import {
  BuildingStorefrontIcon,
  CogIcon,
  ClockIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
} from '@heroicons/react/24/outline';
import api from '../utils/api';
import { DashboardStats } from '../types';
import LoadingSpinner from '../components/LoadingSpinner';

const Dashboard: React.FC = () => {
  const { data: stats, isLoading } = useQuery<DashboardStats>({
    queryKey: ['dashboard-stats'],
    queryFn: async () => {
      const response = await api.get('/dashboard/stats');
      return response.data;
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  const statCards = [
    {
      title: 'Connected Stores',
      value: `${stats?.stores.active || 0} / ${stats?.stores.total || 0}`,
      icon: BuildingStorefrontIcon,
      color: 'text-blue-600',
      bgColor: 'bg-blue-100',
    },
    {
      title: 'Active Rules',
      value: `${stats?.rules.active || 0} / ${stats?.rules.total || 0}`,
      icon: CogIcon,
      color: 'text-green-600',
      bgColor: 'bg-green-100',
    },
  ];

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
        return <CheckCircleIcon className="h-5 w-5 text-green-500" />;
      case 'failed':
        return <ExclamationTriangleIcon className="h-5 w-5 text-red-500" />;
      default:
        return <ClockIcon className="h-5 w-5 text-yellow-500" />;
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-2 text-gray-600">
          Overview of your Shopify order automation system
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {statCards.map((stat, index) => (
          <motion.div
            key={stat.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.1 }}
            className="card"
          >
            <div className="flex items-center">
              <div className={`p-3 rounded-lg ${stat.bgColor}`}>
                <stat.icon className={`h-6 w-6 ${stat.color}`} />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{stat.title}</p>
                <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
              </div>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Recent Activity */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="card"
      >
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-gray-900">Recent Activity</h2>
        </div>

        {stats?.recent_activity && stats.recent_activity.length > 0 ? (
          <div className="space-y-4">
            {stats.recent_activity.map((activity) => (
              <div
                key={activity.id}
                className="flex items-center justify-between p-4 bg-gray-50 rounded-lg"
              >
                <div className="flex items-center space-x-3">
                  {getStatusIcon(activity.status)}
                  <div>
                    <p className="font-medium text-gray-900">
                      Order {activity.order_number}
                    </p>
                    <p className="text-sm text-gray-500">
                      {activity.action.replace(/_/g, ' ')}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-sm text-gray-500">
                    {new Date(activity.created_at).toLocaleDateString()}
                  </p>
                  <p className="text-sm text-gray-500">
                    {new Date(activity.created_at).toLocaleTimeString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8">
            <ClockIcon className="h-12 w-12 text-gray-400 mx-auto mb-4" />
            <p className="text-gray-500">No recent activity</p>
            <p className="text-sm text-gray-400 mt-1">
              Activity will appear here once you set up stores and rules
            </p>
          </div>
        )}
      </motion.div>

      {/* Quick Actions */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="card"
      >
        <h2 className="text-xl font-semibold text-gray-900 mb-6">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <a
            href="/stores"
            className="p-4 border border-gray-200 rounded-lg hover:border-shopify-300 hover:bg-shopify-50 transition-colors"
          >
            <BuildingStorefrontIcon className="h-8 w-8 text-shopify-600 mb-2" />
            <h3 className="font-medium text-gray-900">Connect a Store</h3>
            <p className="text-sm text-gray-500">
              Add your Shopify store to start automation
            </p>
          </a>
          <a
            href="/rules/new"
            className="p-4 border border-gray-200 rounded-lg hover:border-shopify-300 hover:bg-shopify-50 transition-colors"
          >
            <CogIcon className="h-8 w-8 text-shopify-600 mb-2" />
            <h3 className="font-medium text-gray-900">Create a Rule</h3>
            <p className="text-sm text-gray-500">
              Set up automated order processing rules
            </p>
          </a>
        </div>
      </motion.div>
    </div>
  );
};

export default Dashboard;