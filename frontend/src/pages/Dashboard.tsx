import React from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import {
  BuildingStorefrontIcon,
  CogIcon,
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


  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-dark-800">Dashboard</h1>
        <p className="mt-2 text-gray-600 dark:text-dark-500">
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
              <div className={`p-3 rounded-lg ${stat.bgColor} dark:bg-opacity-20`}>
                <stat.icon className={`h-6 w-6 ${stat.color} dark:opacity-80`} />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600 dark:text-dark-500">{stat.title}</p>
                <p className="text-2xl font-bold text-gray-900 dark:text-dark-800">{stat.value}</p>
              </div>
            </div>
          </motion.div>
        ))}
      </div>


      {/* Quick Actions */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="card"
      >
        <h2 className="text-xl font-semibold text-gray-900 dark:text-dark-800 mb-6">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <a
            href="/stores"
            className="p-4 border border-gray-200 dark:border-dark-200 rounded-lg hover:border-shopify-300 hover:bg-shopify-50 dark:hover:bg-shopify-900/20 transition-colors"
          >
            <BuildingStorefrontIcon className="h-8 w-8 text-shopify-600 mb-2" />
            <h3 className="font-medium text-gray-900 dark:text-dark-800">Connect a Store</h3>
            <p className="text-sm text-gray-500 dark:text-dark-400">
              Add your Shopify store to start automation
            </p>
          </a>
          <a
            href="/rules/new"
            className="p-4 border border-gray-200 dark:border-dark-200 rounded-lg hover:border-shopify-300 hover:bg-shopify-50 dark:hover:bg-shopify-900/20 transition-colors"
          >
            <CogIcon className="h-8 w-8 text-shopify-600 mb-2" />
            <h3 className="font-medium text-gray-900 dark:text-dark-800">Create a Rule</h3>
            <p className="text-sm text-gray-500 dark:text-dark-400">
              Set up automated order processing rules
            </p>
          </a>
        </div>
      </motion.div>
    </div>
  );
};

export default Dashboard;