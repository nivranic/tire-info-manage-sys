package org.taiji.tireintelligence.mobile;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** OS scheduler only dispatches checks; the persistent policy remains the authority. */
public final class OfflineSyncWorker extends Worker {
    public OfflineSyncWorker(@NonNull Context context,@NonNull WorkerParameters parameters){super(context,parameters);}
    private static String workName(){return "tire-offline-sync@1:"+BuildConfig.SESSION_NAMESPACE+":"+BuildConfig.API_PORT;}
    static void reconcile(Context context,JSONObject status) throws Exception {
        JSONArray policies=status.getJSONArray("policies");long seconds=Long.MAX_VALUE;
        for(int i=0;i<policies.length();i++){JSONObject policy=policies.getJSONObject(i);if("enabled".equals(policy.getString("state")))seconds=Math.min(seconds,policy.getLong("interval_seconds"));}
        WorkManager manager=WorkManager.getInstance(context.getApplicationContext());
        if(seconds==Long.MAX_VALUE||!BuildConfig.DEBUG){manager.cancelUniqueWork(workName());return;}
        PeriodicWorkRequest request=new PeriodicWorkRequest.Builder(OfflineSyncWorker.class,seconds,TimeUnit.SECONDS)
            .setInitialDelay(seconds,TimeUnit.SECONDS).setConstraints(new Constraints.Builder().build())
            .addTag(workName()).build();
        // Wi-Fi and exact power are re-sampled by the coordinator: WorkManager
        // UNMETERED/charging constraints alone do not establish these conditions.
        manager.enqueueUniquePeriodicWork(workName(),ExistingPeriodicWorkPolicy.UPDATE,request);
    }
    @NonNull @Override public Result doWork(){
        OfflineRuntime runtime=OfflineRuntime.get(getApplicationContext());
        try{
            if(runtime.resetting.get())return Result.success();
            Future<?> task=runtime.syncTasks.submit(()->{
                try{
                    long dispatchDeadline=android.os.SystemClock.elapsedRealtime()+240000;
                    for(int turn=0;turn<16&&!isStopped()&&!runtime.resetting.get()&&android.os.SystemClock.elapsedRealtime()<dispatchDeadline;turn++) {
                        JSONObject status=runtime.store().syncStatus(false);JSONArray policies=status.getJSONArray("policies");JSONObject selected=null;java.time.Instant now=java.time.Instant.now();
                        for(int i=0;i<policies.length();i++){
                            JSONObject policy=policies.getJSONObject(i);
                            if("enabled".equals(policy.getString("state"))&&!policy.isNull("next_due_at")&&!now.isBefore(java.time.Instant.parse(policy.getString("next_due_at")))&&
                                (selected==null||policy.getString("next_due_at").compareTo(selected.getString("next_due_at"))<0))selected=policy;
                        }
                        if(selected==null)break;
                        runtime.run(OfflineSyncValues.json("policy_id",selected.getString("policy_id"),"expected_policy_revision",selected.getLong("policy_revision"),"trigger","os_job"),()->OfflineSyncConditions.sample(getApplicationContext()));
                    }
                    reconcile(getApplicationContext(),runtime.store().syncStatus(false));
                }catch(Exception ignored){/* No network retry on unknown writes. Durable journal is recovered/paused by the next status. */}
            });
            task.get(540,TimeUnit.SECONDS);return Result.success();
        }catch(java.util.concurrent.RejectedExecutionException ignored){return Result.success();}
        catch(InterruptedException ignored){Thread.currentThread().interrupt();return Result.success();}
        catch(Exception ignored){return Result.success();}
    }
}
