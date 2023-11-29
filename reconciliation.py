# -----------------------------
__file__ = 'reconciliation.py'
__doc__ = """
"""

# -----------------------------
import multiprocessing
from multiprocessing import Pool
import time
import os
import queue
from decimal import Decimal
import json

# from utils.utils_reconciliation import receding_horizon_2d_l1, resample, receding_horizon_2d, combine_fragments, rectify_2d
from utils.utils_opt import combine_fragments, resample, opt1, opt2, opt1_l1, opt2_l1, opt2_l1_constr
    

# Custom JSON encoder to handle Decimal objects
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return str(o)  # Convert Decimal to a string representation
        return super().default(o)
    
    
def reconcile_single_trajectory(reconciliation_args, combined_trajectory, reconciled_queue) -> None:
    """
    Resample and reconcile a single trajectory, and write the result to a queue
    :param next_to_reconcile: a trajectory document
    :return:
    """
    

    resampled_trajectory = resample(combined_trajectory, dt=0.04)
    if "post_flag" in resampled_trajectory:
        # skip reconciliation
        print("+++ Flag as low conf, skip reconciliation")

    else:
        try:
            finished_trajectory = opt2_l1_constr(resampled_trajectory, **reconciliation_args)  
            reconciled_queue.put(finished_trajectory)
           
        except Exception as e:
            print("+++ Flag as {}, skip reconciliation".format(str(e)))



def reconciliation_pool(parameters, db_param, stitched_trajectory_queue: multiprocessing.Queue, 
                        reconciled_queue: multiprocessing.Queue, ) -> None:
    """
    Start a multiprocessing pool, each worker 
    :param stitched_trajectory_queue: results from stitchers, shared by mp.manager
    :param pid_tracker: a dictionary
    :return:
    """

    n_proc = min(multiprocessing.cpu_count(), parameters["worker_size"])
    worker_pool = Pool(processes= n_proc)

    
    # parameters
    reconciliation_args=parameters["reconciliation_args"]

    # wait to get raw collection name
    while parameters["raw_collection"]=="":
        time.sleep(1)
    
    print("** Reconciliation pool starts. Pool size: {}".format(n_proc))
    TIMEOUT = parameters["reconciliation_pool_timeout"]
    
    cntr = 0
    while True:
        try:
            try:
                traj_docs = stitched_trajectory_queue.get(timeout = TIMEOUT) #20sec
                cntr += 1
            except queue.Empty: 
                print("Reconciliation pool is timed out after {}s. Close the reconciliation pool.".format(TIMEOUT))
                worker_pool.close()
                break
            if isinstance(traj_docs, list):
                combined_trajectory = combine_fragments(traj_docs)
            else:
                combined_trajectory = combine_fragments([traj_docs])
            # combined_trajectory = combine_fragments(traj_docs)  
            worker_pool.apply_async(reconcile_single_trajectory, (reconciliation_args, combined_trajectory, reconciled_queue, ))

        except Exception as e: # other exception
            print("{}, Close the pool".format(e))
            worker_pool.close() # wait until all processes finish their task
            break
            
            
        
    # Finish up  
    worker_pool.join()
    print("Joined the pool.")
    
    return



def write_reconciled_to_db(parameters, db_param, reconciled_queue):
    
        
    TIMEOUT = parameters["reconciliation_writer_timeout"]
    cntr = 0
    HB = parameters["log_heartbeat"]
    begin = time.time()

    # in case of restart, remove the last "]" in json
    output_filename = parameters["reconciled_collection"]+".json"
    file_exists = os.path.exists(output_filename)
    append_flag = file_exists and os.stat(output_filename).st_size > 0
    
    if append_flag:
        with open(output_filename, 'rb+') as fh:
            fh.seek(-1, os.SEEK_END)
            fh.truncate()
        print("removed last character")

    # Write to db
    while True:

        try:
            record = reconciled_queue.get(timeout = TIMEOUT)
        except queue.Empty:
            print("Getting from reconciled_queue reaches timeout {} sec.".format(TIMEOUT))
            break

        # TODO: write one
        file_exists = os.path.exists(output_filename)
        append_flag = file_exists and os.stat(output_filename).st_size > 0

        # Open the output file for writing or appending
        with open(output_filename, 'a' if file_exists else 'w') as output_file:
            # If the file doesn't exist or is empty, write the start of the JSON array
            if not append_flag:
                output_file.write("[")

            # Check if the file already had data and adjust the comma if needed
            first_item = True if not file_exists or os.stat(output_filename).st_size == 0 else False

            if not first_item:
                output_file.write(",")  # Separate items with commas except for the first one
            else:
                first_item = False
            
            # Write each record (dictionary) to the output file using the custom encoder
            json.dump(record, output_file, cls=DecimalEncoder)
            cntr += 1
            output_file.write("]")  # Close the JSON array
        

        if time.time()-begin > HB:
            begin = time.time()
            
            # TODO: progress update
            print(f"Writing {cntr} documents in this batch")
            

    
    # Safely close the mongodb client connection
    print(f"JSON writer closed. Current count: {cntr}. Exit")
    return



    
    
    
    
    
    

if __name__ == '__main__':
    print("not implemented")
